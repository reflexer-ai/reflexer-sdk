/**
 * Amazon Bedrock, through reflexer, apart from the files every provider shares: a direct call to OpenAI or Anthropic
 * runs as shipped. A call carrying a Bedrock API key (`Authorization: Bearer`) goes to reflexer, the key among its
 * headers; so does a call signed by SigV4, as signed, where its fallback can be signed anew after reflexer's leg: by AWS
 * JS's own signer (`wrap`), or by AnthropicBedrock making its attempt again (`anthropicMiddleware`). Elsewhere a signed
 * call goes to Bedrock as its library made it. Three lines: `fetch`, for the SDKs that take one (AnthropicBedrock; the
 * AI SDK's is `./bedrock-ai.js`'s, built on it), with AnthropicBedrock's middleware; `wrap`, AWS JS's `requestHandler`
 * around the client's own.
 */
import { AsyncLocalStorage } from "node:async_hooks";
import { HEADERS_TIMEOUT, provider, textOf } from "./index.js";
import { BASE, OURS, Reflexer, ReplayNotTaken, SKIP, isReplay, skips, skipsByOption } from "./logic.js";

export const WIRE = { reflexerPath: "/bedrock", calls: /\/model\/[^/]+\/(invoke|invoke-with-response-stream|converse|converse-stream)$/ };
const STREAMED = /\/(invoke-with-response-stream|converse-stream)$/; // the wire's streamed calls
const call = new AsyncLocalStorage(); // a call's own, set around it by our middleware: { skipped, seen }

/**
 * The Bedrock libraries this is tested on, as `SDKS` lists the provider SDKs: their majors, the oldest release tested,
 * and how their calls name it. AWS JS's calls name the release before its own; AnthropicBedrock's, the SDK it is built on.
 */
export const LIBRARIES = [
  { name: "@aws-sdk/client-bedrock-runtime", majors: [3], floor: "3.1160.0", label: /\bapi\/bedrock-runtime#([0-9.]+)/ },
  { name: "@ai-sdk/amazon-bedrock", majors: [5], floor: "5.0.132", label: /\bai-sdk-amazon-bedrock\/([0-9.]+)/ },
  { name: "@anthropic-ai/sdk", majors: [1], floor: "1.0.0", label: /\bAnthropicBedrock\/JS ([0-9.]+)/ },
];

/** A call naming a release of a library not tested throws, never misroutes. @param {Headers} headers */
function tested(headers) {
  const sortable = (/** @type {string} */ text) => text.split(".").map((part) => part.padStart(9, "0")).join("."); // in text order as in version order
  for (const { name, majors, floor, label } of LIBRARIES) {
    const version = label.exec(`${headers.get("user-agent") ?? ""} ${headers.get("x-amz-user-agent") ?? ""}`)?.[1]; // a browser's, the second
    if (version && (!majors.includes(Number(version.split(".")[0])) || sortable(version) < sortable(floor))) {
      throw new Error(`reflexer is tested on ${name} ${majors} from ${floor}, not ${version}`);
    }
  }
  return headers;
}

/** Whether a call carries a Bedrock API key, not a signature. @param {Headers} headers */
const keyed = (headers) => /^Bearer /i.test(headers.get("authorization") ?? "");

/** Whether its library signed the call by SigV4, AWS's signature, which holds a few minutes from its signing time. @param {Headers} headers */
export const signed = (headers) => /^AWS4-HMAC-SHA256 /.test(headers.get("authorization") ?? "");

/** `run()` as a call our middleware skipped: it goes straight. @template T @param {() => T} run */
export const skipped = (run) => call.run({ skipped: true }, run);

/** Thrown in place of a signed call's straight leg under AnthropicBedrock's middleware, which makes the attempt again. */
class Again extends Error {}

/**
 * The client's own call, straight. A signed one goes as its library made it: a header taken off would break its
 * signature. A replay never goes.
 * @param {(input: any, init: any) => Promise<any>} send @param {any} input @param {any} init
 */
function straight(send, input, init) {
  const body = textOf(init.body);
  if (body !== undefined && isReplay(body)) throw new ReplayNotTaken("reflexer did not accept this replay, and the SDK never sends a replay to the provider");
  const headers = new Headers(init.headers);
  if (!keyed(headers)) return send(input, init);
  for (const name of [...headers.keys()].filter((name) => name.startsWith(OURS))) headers.delete(name);
  return send(input, { ...init, headers });
}

/**
 * `start(signal)`, cut when its answer has not started within `ms`; once it starts, it runs as the client's own would.
 * `given`: the client's own signal, joined.
 * @template T @param {(signal: AbortSignal) => Promise<T>} start @param {AbortSignal | null | undefined} given @param {number} ms
 * @returns {Promise<T>}
 */
async function bounded(start, given, ms) {
  const late = new AbortController();
  const clock = setTimeout(() => late.abort(new DOMException("the answer did not start in time", "TimeoutError")), ms);
  try {
    return await start(given ? AbortSignal.any([given, late.signal]) : late.signal);
  } finally {
    clearTimeout(clock);
  }
}

/**
 * The shipped `fetch` line on Bedrock's wire, for a call carrying a key, and for a signed one under AnthropicBedrock's
 * middleware, whose straight leg the middleware makes again (`Again`), or given `options.signed`, whose fallback reuses
 * its signature (the AI SDK's line bounds reflexer's leg by its window). Any other call, or one a middleware skipped,
 * goes straight by the client's own `fetch`. When the client's own signal cuts reflexer's leg with a `TimeoutError` (the
 * AI SDK's every timeout, and `AbortSignal.timeout`'s), a call not streamed goes straight, given as long again: a
 * stream's caller has ended it already, above any line. AnthropicBedrock's timer cuts with no reason: its middleware
 * tells it from a cancel (`anthropicMiddleware`).
 * @param {string} key @param {any} [options] `{ base, sample, namespace, fetch, headersTimeout, signed }`
 */
export function fetch(key, options = {}) {
  const own = (/** @type {any} */ input, /** @type {any} */ init) => (options.fetch ?? globalThis.fetch)(input, init);
  const base = new URL(options.base ?? BASE).origin;
  const inner = (/** @type {any} */ input, /** @type {any} */ init = {}) => {
    const store = call.getStore(), ours = String(input).startsWith(base);
    if (store?.again && !ours && !store.again.sent) return straight(own, input, store.again.init); // reflexer's leg never sent: as signed
    if (store?.again && !ours) { // a signed call's straight leg after reflexer's: the middleware makes the attempt again
      store.again.straight = true;
      throw new Again("the call goes straight, signed anew");
    }
    if (store?.again) store.again.sent = true;
    return own(input, init).catch((/** @type {any} */ failure) => {
      if (store?.seen && String(input).startsWith(base) && init.signal?.aborted) store.seen.cut = init.signal.reason ?? true; // reflexer's leg, cut by the client
      throw failure;
    });
  };
  const routed = provider(WIRE).fetch(key, { ...options, fetch: inner });
  return async (/** @type {any} */ input, /** @type {any} */ init = {}) => {
    const store = call.getStore();
    const headers = tested(new Headers(init.headers));
    skips(headers.get(SKIP)); // a wrong value throws here, before anything is sent
    if (store?.skipped || !(keyed(headers) || (signed(headers) && (store?.again || options.signed)))) return straight(own, input, init);
    if (init.signal?.aborted) return routed(input, init); // the client's own signal ended before reflexer's leg: as shipped
    const seen = store?.seen ?? {};
    const began = performance.now();
    try {
      const again = signed(headers) ? store?.again : undefined; // a keyed call falls back here
      if (again) again.init = init;
      return await call.run({ ...store, seen, again }, () => routed(input, init));
    } catch (failure) {
      if (/** @type {any} */ (seen).cut?.name !== "TimeoutError" || STREAMED.test(new URL(String(input)).pathname)) throw failure;
      return straight(own, input, { ...init, signal: AbortSignal.timeout(Math.max(Math.ceil(performance.now() - began), 1)) });
    }
  };
}

/**
 * AnthropicBedrock's own middleware. The skip header, taken off before the SDK signs; the call then goes straight. A
 * signed call's straight leg is not sent after reflexer's: `next` again, straight, which the SDK signs anew. The SDK
 * arms its timeout around each inner fetch and cuts with no reason, as a cancel does; the middleware, above that timer,
 * sees the client's own signal (`ctx.options.signal`): reflexer's leg cut while it is not aborted was cut by the timer,
 * so `next` again, straight, with the client's timeout afresh and its cancel kept.
 */
export async function anthropicMiddleware(/** @type {any} */ request, /** @type {any} */ next, /** @type {any} */ ctx) {
  const headers = new Headers(request.headers), skip = skips(headers.get(SKIP)); // "false", as with no header; any other value but "true" throws, before anything is sent
  if (headers.has(SKIP)) headers.delete(SKIP), request = { ...request, headers };
  if (skip) return skipped(() => next(request));
  const seen = { cut: undefined }, again = { straight: false, sent: false, init: {} };
  try {
    return await call.run({ seen, again }, () => next(request));
  } catch (failure) {
    const options = ctx?.options ?? {};
    if (seen.cut && !options.signal?.aborted && options.timeout) {
      return bounded((signal) => skipped(() => next({ ...request, signal })), options.signal, options.timeout);
    }
    if (!again.straight || seen.cut) throw failure;
    return skipped(() => next(request));
  }
}

/**
 * AWS JS's `requestHandler` option: ours around the client's own handler, which carries both legs. Reflexer's leg is a
 * copy of the request, keyed or signed, bounded to its answer's head as the `fetch` line is; the client's own request
 * never holds the key. A signed call goes to reflexer only given `signer`, the client's own, which signs its straight leg
 * anew after reflexer's (`wrap` gives it). The skip as `send`'s option: `client.send(command, { reflexerSkip: true })`.
 * @param {string} key @param {any} options `{ handler, signer, base, sample, namespace, headersTimeout }`
 */
export function requestHandler(key, { handler, signer, ...options }) {
  if (HANDLERS.has(handler)) throw new Error("this handler already sends its calls through reflexer"); // twice, a call would try reflexer twice
  if (!FOLLOWS_NO_REDIRECT.includes(handler?.metadata?.handlerProtocol)) throw new Error("reflexer works only with the Node HTTP handlers of the AWS SDK for JavaScript, which do not follow redirects: this handler could send the key to the target of a redirect");
  const ask = asking(new Reflexer(key, WIRE, options), handler, options.headersTimeout ?? HEADERS_TIMEOUT);
  const made = {
    /** @param {any} request @param {any} [given] */
    async handle(request, { reflexerSkip, ...given } = {}) {
      const headers = tested(new Headers(plain(request.headers)));
      skips(headers.get(SKIP)); // a wrong value throws here, before anything is sent
      skipsByOption(reflexerSkip, NOT_A_SKIP_OPTION); // as does a wrong option
      if (!keyed(headers) && !(signer && signed(headers))) return handler.handle(smithyStaysStraight(request), given);
      const { response, sent } = reflexerSkip ? { response: null, sent: false } : await ask(request, given);
      if (response) return { response };
      return handler.handle(sent && signed(headers) ? await signedAnew(signer, smithyStaysStraight(request)) : smithyStaysStraight(request), given);
    },
    /** @param {any} name @param {any} value */
    updateHttpClientConfig: (name, value) => handler.updateHttpClientConfig(name, value),
    httpHandlerConfigs: () => handler.httpHandlerConfigs(),
    metadata: handler.metadata, // its protocol, which the signer reads: HTTP/2 signs `:authority`
  };
  HANDLERS.set(made, true);
  return made;
}
/**
 * Reflexer's leg on AWS JS: its answer, or null to go straight, and whether it was sent. The line's state is this closure's, not the client's
 * call's: an error thrown to the client shows no frame of ours holding the key.
 * @param {Reflexer} reflexer @param {any} handler @param {number} bound
 */
function asking(reflexer, handler, bound) {
  return async (/** @type {any} */ request, /** @type {any} */ given) => {
    let sent = false;
    try {
      const ours = smithyToReflexer(reflexer, request);
      if (!ours) return { response: null, sent };
      sent = true;
      // the client's own timeouts hold, as its handler applies them; ours bounds the answer's head, as the fetch line's
      const { response } = await bounded((abortSignal) => handler.handle(ours, { ...given, abortSignal }), given.abortSignal, bound);
      if (!reflexer.goesStraight(response.statusCode, new Headers(plain(response.headers)))) return { response, sent };
      response.body?.destroy?.();
    } catch (failure) {
      reflexer.failed(failure);
    }
    return { response: null, sent };
  };
}
const HANDLERS = new WeakMap(); // each handler made here
const FOLLOWS_NO_REDIRECT = ["http/1.1", "h2"]; // Smithy's Node handlers' protocols, by their metadata; its fetch handler names none
const NOT_A_SKIP_OPTION = "the reflexerSkip option must be true or false: true sends the call directly to the provider, false lets the call go through reflexer";
const SIGNATURE = ["authorization", "x-amz-date", "x-amz-security-token"]; // what AWS JS's signer sets anew

/**
 * A signed straight request, signed anew by `signer` after reflexer's leg; as first signed if the signer fails.
 * @param {(request: any) => Promise<any>} signer @param {any} request
 */
async function signedAnew(signer, request) {
  const first = { ...request.headers };
  try {
    return await signer(request);
  } catch {
    request.headers = first;
    return request;
  }
}

/**
 * The one line on a client made elsewhere: its own handler, from its resolved config, wrapped by ours, and its own
 * signer, at its own clock (AWS JS corrects it by each answer's `Date`), for a signed call's straight leg. The skip as a
 * header the client's middleware sets: taken off just before signing, put back after, unsigned, for the handler.
 * @template C @param {C} client @param {string} key @param {any} [options] @returns {C}
 */
export function wrap(client, key, options = {}) {
  const config = /** @type {any} */ (client).config;
  const signer = async (/** @type {any} */ request) => {
    request.headers = Object.fromEntries(Object.entries(request.headers).filter(([name]) => !SIGNATURE.includes(name)));
    return (await config.signer()).sign(request, { signingDate: (Date.now() + (config.systemClockOffset ?? 0)) / 1000 }); // seconds, as Smithy reads a number
  };
  config.requestHandler = requestHandler(key, { ...options, handler: config.requestHandler, signer });
  const skippedCalls = new WeakMap(); // each skipped call's context, Smithy's own per call
  const stack = /** @type {any} */ (client).middlewareStack;
  stack.addRelativeTo((/** @type {any} */ next, /** @type {any} */ context) => (/** @type {any} */ args) => {
    const headers = Object.entries(args.request?.headers ?? {});
    const given = headers.filter(([name]) => name.toLowerCase() === SKIP).map(([, value]) => skips(value)); // a wrong value throws, before anything is sent
    if (given.length) args.request.headers = Object.fromEntries(headers.filter(([name]) => name.toLowerCase() !== SKIP));
    if (given.includes(true)) skippedCalls.set(context, true);
    return next(args);
  }, { relation: "before", toMiddleware: "httpSigningMiddleware", name: "reflexerSkipBeforeSigning" });
  stack.add((/** @type {any} */ next, /** @type {any} */ context) => (/** @type {any} */ args) => {
    if (skippedCalls.has(context)) args.request.headers = { ...args.request.headers, [SKIP]: "true" };
    return next(args);
  }, { step: "deserialize", priority: "low", name: "reflexerSkipAfterSigning" });
  return client;
}

/** @param {any} reflexer @param {any} request a Smithy HttpRequest, keyed */
function smithyToReflexer(reflexer, request) {
  const body = textOf(request.body);
  if (body === undefined) return null;
  const address = new URL(`${request.protocol}//${request.hostname}${request.port ? `:${request.port}` : ""}${request.path}`);
  for (const [k, v] of Object.entries(request.query ?? {})) for (const x of Array.isArray(v) ? v : [v]) address.searchParams.append(k, x);
  const route = reflexer.route(address.href, Object.fromEntries(new Headers(plain(request.headers))), isReplay(body));
  if (!route) return null;
  const to = new URL(route[0]);
  return { ...request, protocol: to.protocol, hostname: to.hostname, port: to.port ? Number(to.port) : undefined, path: to.pathname,
    query: Object.fromEntries(to.searchParams), headers: route[1] };
}

/**
 * A Smithy request's headers but the HTTP/2 pseudo-headers: `:authority`, signed over HTTP/2 in place of `host`, is
 * reflexer's own on reflexer's leg, as `host` is.
 * @param {Record<string, string>} headers
 */
function plain(headers) {
  return Object.fromEntries(Object.entries(headers).filter(([name]) => !name.startsWith(":")));
}

/**
 * The client's own request, for Bedrock: the skip's header, put back unsigned, taken off; on a keyed call, every header
 * of ours; a signed call's own headers stay, as signed. A replay never goes.
 * @param {any} request
 */
function smithyStaysStraight(request) {
  const body = textOf(request.body);
  if (body !== undefined && isReplay(body)) throw new ReplayNotTaken("reflexer did not accept this replay, and the SDK never sends a replay to the provider");
  const ours = keyed(new Headers(plain(request.headers))) ? OURS : SKIP;
  request.headers = Object.fromEntries(Object.entries(request.headers).filter(([name]) => !name.toLowerCase().startsWith(ours)));
  return request;
}

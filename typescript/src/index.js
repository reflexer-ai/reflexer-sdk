/**
 * Reflexer's SDK: a `fetch` for the provider SDK's own `fetch` option. Each call goes where `Reflexer.route` says, by the
 * client's own `fetch`, so its proxy, TLS and connections hold. Whatever fails on the way to reflexer, the client's own call
 * still goes. No answer is touched.
 */
import { BASE, OURS, Reflexer, ReplayNotTaken, SKIP, bounded, checked, isReplay } from "./logic.js";

export * from "./logic.js";

/** @typedef {import("./logic.js").Wire} Wire */
/** @typedef {(input: string | URL | Request, init?: RequestInit) => Promise<Response>} Fetch */
/** @typedef {{ key: string, base?: string, sample?: number, namespace?: string, answer?: boolean, store?: boolean, passThrough?: boolean, timeoutMs?: number, fetch?: Fetch, headersTimeout?: number }} Way */

/** The wire formats: each provider's call paths, and reflexer's path for them. */
export const WIRES = {
  openai: { reflexerPath: "/openai", provider: "https://api.openai.com", calls: /\/v1\/(chat\/completions|responses)$/,
    routers: [ // a router's own body keys are served on its own route; its other calls go as any base's
      { host: "openrouter.ai", reflexerPath: "/openrouter", provider: "https://openrouter.ai", calls: /\/api\/v1\/chat\/completions$/ },
      { host: "ai-gateway.vercel.sh", reflexerPath: "/vercel", provider: "https://ai-gateway.vercel.sh", calls: /\/v1\/chat\/completions$/ },
    ] },
  azure: { reflexerPath: "/azure", calls: /\/openai\/((deployments\/[^/]+|v1)\/(chat\/completions|responses)|responses)$/ }, // its own host, always named; the last, Azure's dated Responses
  anthropic: { reflexerPath: "/anthropic", provider: "https://api.anthropic.com", calls: /\/v1\/messages$/ },
  gemini: { reflexerPath: "/gemini", provider: "https://generativelanguage.googleapis.com",
    calls: /\/v1(alpha|beta)?\/models\/[^/]+:(stream)?[gG]enerateContent$/ },
};

const STREAMED = /(:streamGenerateContent|\/invoke-with-response-stream|\/converse-stream)$/; // a streamed call's last path segment: Gemini's, Bedrock's; the others say `"stream": true` in their body
const KEPT = ["method", "signal", "dispatcher"]; // of a client's request options, what reflexer's request keeps
export const HEADERS_TIMEOUT = 300_000; // ms reflexer's leg waits for its answer to start: undici's own default, provisional
const WAYS = new WeakMap(); // each fetch made here, and its way, for an SDK's copy of a client
const CUT = new WeakMap(); // each client's signal that ended during reflexer's leg, as a key


/**
 * A `fetch` that sends a provider's calls through reflexer: give it as the provider SDK's `fetch` option.
 * `way.fetch`, the client's own, carries both legs; by default the global one, as the provider SDK's default.
 * @param {Wire} wire
 * @param {Way} way
 * @returns {Fetch}
 */
function through(wire, way) {
  const reflexer = new Reflexer(way.key, wire, way);
  /** @type {Fetch} */
  const send = (input, init) => (way.fetch ?? globalThis.fetch)(input, init);

  /** @type {Fetch} */
  async function routed(input, init = {}) {
    tested(new Headers(init.headers));
    checked(new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined))); // a wrong value throws here, before anything is sent
    const streamed = STREAMED.test(String(input).split(/[?#]/)[0]) || /"stream":\s*true/.test(textOf(init.body) ?? ""); // after a timeout, its caller has ended it already
    const live = !init.signal?.aborted; // the client's own signal, still live as reflexer's leg starts
    const began = live && !streamed ? performance.now() : null;
    try {
      const ours = toReflexer(reflexer, input, init);
      if (ours) {
        const answer = await bounded((signal) => send(ours[0], { ...ours[1], signal }), ours[1].signal, way.headersTimeout ?? HEADERS_TIMEOUT, "reflexer's answer did not start in time"); // a reflexer that hangs still falls back, whatever the client's own timeout
        if (!reflexer.goesStraight(answer.status, answer.headers)) return answer;
        await answer.body?.cancel();
      }
    } catch (failure) {
      if (live && init.signal?.aborted) CUT.set(init.signal, true);
      reflexer.failed(failure);
    }
    const signal = afresh(init.signal, began);
    return send(...staysStraight(input, signal === init.signal ? init : { ...init, signal })); // no `signal` key added: it would drop a `Request`'s own
  }

  WAYS.set(routed, way);
  return routed;
}

/**
 * The client's own signal, or, when it ended by a timeout (`TimeoutError`: `AbortSignal.timeout`'s, the AI SDK's) after
 * `began`, during reflexer's leg, a timeout as long as it ran since: the call reaches the provider, and can take up to twice
 * the client's timeout. Any other abort is a cancel, kept. A cancel of the client's can no longer reach the new timeout's call.
 * @param {AbortSignal | null | undefined} signal @param {number | null} began
 */
export function afresh(signal, began) {
  return began !== null && signal?.reason?.name === "TimeoutError" ? AbortSignal.timeout(Math.max(Math.ceil(performance.now() - began), 1)) : signal;
}

/**
 * Its text, or undefined for a body that could not be sent twice, such as a stream: it goes straight.
 * @param {RequestInit["body"]} body
 */
export function textOf(body) {
  if (body == null) return "";
  if (typeof body === "string") return body;
  if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) return new TextDecoder().decode(body);
  return undefined;
}

/**
 * The call as it goes to reflexer, or null. The client's own request stays as it was.
 * @param {Reflexer} reflexer
 * @param {string | URL | Request} input
 * @param {RequestInit} init
 * @returns {[string, RequestInit] | null}
 */
function toReflexer(reflexer, input, init) {
  const body = textOf(init.body);
  if (input instanceof Request || body === undefined) return null; // a body inside a `Request` is a stream
  const route = reflexer.route(String(input), Object.fromEntries(new Headers(init.headers)), isReplay(body));
  if (!route) return null;
  const kept = Object.fromEntries(Object.entries(init).filter(([name]) => KEPT.includes(name))); // no callback of theirs sees our key
  return [route[0], { ...kept, headers: route[1], body: init.body, redirect: "manual" }]; // a redirect goes straight
}

/**
 * The client's own call, for its provider: no header of ours leaves. A replay never does: the one call that cannot fall back.
 * @param {string | URL | Request} input
 * @param {RequestInit} init
 * @returns {[string | URL | Request, RequestInit]}
 */
function staysStraight(input, init) {
  const body = textOf(init.body);
  if (body !== undefined && isReplay(body)) throw new ReplayNotTaken("reflexer did not accept this replay, and the SDK never sends a replay to the provider");
  const headers = new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined));
  for (const name of [...headers.keys()].filter((name) => name.startsWith(OURS))) headers.delete(name);
  return [input, { ...init, headers }];
}

/**
 * One provider's `fetch` maker: `openai.fetch(reflexerKey)`, with `{ base, sample, namespace, answer, store, passThrough, timeoutMs, fetch }` as options.
 * `stock`, the `fetch` its SDK uses when given none, if not the global one.
 * @param {Wire} wire
 * @param {Fetch} [stock]
 */
export function provider(wire, stock) {
  return {
    /** @param {string} key @param {Omit<Way, "key">} [options] */
    fetch: (key, options = {}) => through(wire, { ...options, key, fetch: options.fetch ?? stock }),
  };
}

/**
 * As google-genai's own, on Node and given no fetch: Node's global dispatcher, kept where undici documents it, without
 * undici's 300 s timeouts. Reflexer's leg keeps a bound of its own (`bounded`).
 */
const untimed = {
  /** @param {object} options @param {object} handler */
  dispatch(options, handler) {
    new Headers(); // Node makes its global dispatcher on first use
    return /** @type {any} */ (globalThis)[Symbol.for("undici.globalDispatcher.1")].dispatch({ ...options, headersTimeout: 0, bodyTimeout: 0 }, handler);
  },
};

export const openai = provider(WIRES.openai);
export const azure = provider(WIRES.azure);
export const anthropic = provider(WIRES.anthropic);
export const gemini = provider(WIRES.gemini, (input, init) => globalThis.fetch(input, { dispatcher: /** @type {any} */ (untimed), ...init }));

/**
 * Each provider SDK's majors this is tested on, its oldest release tested, and how its calls name its version, in their
 * user agent. google-genai takes a `fetch` from 2.23.0, and adds its untimed dispatcher, which reflexer's line keeps, from 2.29.0.
 */
export const SDKS = [
  { name: "openai", majors: [7], floor: "7.0.0", label: /OpenAI\/JS ([0-9.]+)/ },
  { name: "@anthropic-ai/sdk", majors: [1], floor: "1.0.0", label: /Anthropic\/JS ([0-9.]+)/ },
  { name: "@google/genai", majors: [2], floor: "2.29.0", label: /\bgoogle-genai-sdk\/([0-9.]+)/ },
];

/**
 * A provider SDK runs only on the majors it was tested on, from its floor: a new major, or an older release, throws, never misroutes.
 * @param {string} name @param {string} version
 */
export function supported(name, version) {
  const { majors, floor } = /** @type {typeof SDKS[0]} */ (SDKS.find((sdk) => sdk.name === name));
  const sortable = (/** @type {string} */ text) => text.split(".").map((part) => part.padStart(9, "0")).join("."); // in text order as in version order
  const fails = !majors.includes(Number(version.split(".")[0])) || sortable(version) < sortable(floor);
  if (fails) throw new Error(`reflexer is tested on ${name} ${majors} from ${floor}, not ${version}`);
}

/**
 * The provider SDKs a call's user agent names, each checked by `supported`. A call naming none goes as before: the fetch
 * form takes a provider's calls from any client.
 * @param {Headers} headers
 */
export function tested(headers) {
  const label = `${headers.get("user-agent") ?? ""} ${headers.get("x-goog-api-client") ?? ""}`;
  const named = SDKS.map(({ name, label: pattern }) => [name, pattern.exec(label)?.[1]]).filter(([, version]) => version);
  for (const [name, version] of named) supported(String(name), String(version));
  return named.map(([name]) => name);
}

/**
 * The middleware `client` adds for an SDK that arms its timeout around each inner fetch and cuts with no reason, as a
 * cancel does (@anthropic-ai/sdk). Above that timer it sees the client's own signal (`ctx.options.signal`): reflexer's leg
 * cut while that signal is live was cut by the timer, so `next` again, straight, with the client's whole timeout to the
 * answer's start, as the SDK's own timer, and its cancel joined. Its caller waits, streamed too. A middleware of the
 * client's that swaps `request.signal` for one of its own and aborts it reads here as a timeout; a per-request one, inside
 * this, that swaps it makes the check miss: the call fails as before.
 * @param {any} request @param {any} next @param {any} ctx
 */
async function afterTimeout(request, next, ctx) {
  try {
    return await next(request);
  } catch (failure) {
    const { signal, timeout } = ctx?.options ?? {};
    if (!CUT.has(request.signal) || signal?.aborted || !timeout) throw failure;
    const headers = new Headers(request.headers);
    headers.set(SKIP, "true"); // straight: the line takes it off
    return bounded((cut) => next({ ...request, headers, signal: cut }), signal, timeout);
  }
}

/**
 * @template {abstract new (...args: any) => any} C
 * @typedef {(new (options?: ConstructorParameters<C>[0] & { reflexerKey?: string, reflexerBase?: string, sample?: number, reflexerNamespace?: string, reflexerAnswer?: boolean, reflexerStore?: boolean, reflexerPassThrough?: boolean, reflexerTimeoutMs?: number }) => InstanceType<C>) & C} Reflexed
 */

/**
 * The one line: `new Stock(config)` becomes `new Client({ ...config, reflexerKey })`, for an SDK client class whose
 * options take `fetch` and whose copies are made by `withOptions`. The SDK's own copies hand our `fetch` back in, with no
 * key; a copy given a `fetch` of the client's goes through reflexer the same way.
 * @template {new (options?: any) => { withOptions(options: any): any }} C
 * @param {C} Stock
 * @param {Wire} wire
 * @param {{ middleware?: boolean }} [options] `middleware`: add `afterTimeout`, after the client's own, for an SDK whose middleware runs above its timer (@anthropic-ai/sdk's)
 * @returns {Reflexed<C>}
 */
export function client(Stock, wire, { middleware = false } = {}) {
  // @ts-ignore: a mixin's constructor takes the stock options, and ours
  class Client extends Stock {
    #way;

    /** @param {any} options */
    constructor({ reflexerKey, reflexerBase = BASE, sample = 1, reflexerNamespace, reflexerAnswer, reflexerStore, reflexerPassThrough, reflexerTimeoutMs, ...config } = {}) {
      const options = { answer: reflexerAnswer, store: reflexerStore, passThrough: reflexerPassThrough, timeoutMs: reflexerTimeoutMs };
      const routed = WAYS.has(config.fetch) ? config.fetch : through(wire, { key: reflexerKey, base: reflexerBase, sample, namespace: reflexerNamespace, ...options, fetch: config.fetch });
      const own = config.middleware ?? [];
      super({ ...config, fetch: routed, ...(middleware && { middleware: own.includes(afterTimeout) ? own : [...own, afterTimeout] }) }); // a copy is given ours back
      this.#way = WAYS.get(routed);
    }

    /** @param {any} options */
    withOptions(options) {
      const own = options?.fetch;
      return super.withOptions(own === undefined || WAYS.has(own) ? options : { ...options, fetch: through(wire, { ...this.#way, fetch: own }) });
    }
  }

  Object.defineProperty(Client, "name", { value: Stock.name }); // the SDK names its client by it, in its user agent
  return /** @type {any} */ (Client);
}

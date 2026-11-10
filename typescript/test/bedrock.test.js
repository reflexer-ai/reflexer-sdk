// Amazon Bedrock's lines, on their real libraries over a mock `fetch` or a mock request handler, offline; every value
// made up. A call with a Bedrock API key goes to reflexer; so does a call signed by SigV4, its fallback signed anew by
// its library (AWS JS, LangChain.js, AnthropicBedrock) or, on the AI SDK, reflexer's leg bounded by its window. Bedrock's
// mock judges each signature as Bedrock does: recomputed by Smithy's own signer, its time within the window.
import assert from "node:assert/strict";
import { Sha256 } from "@aws-crypto/sha256-js";
import { HttpRequest } from "@smithy/protocol-http";
import { SignatureV4 } from "@smithy/signature-v4";
import { readFileSync } from "node:fs";
import { Readable } from "node:stream";
import { describe, test } from "node:test";
import { AnthropicBedrock } from "@anthropic-ai/bedrock-sdk";
import { BedrockRuntimeClient, ConverseCommand, ConverseStreamCommand, CountTokensCommand, InvokeModelCommand,
  InvokeModelWithResponseStreamCommand } from "@aws-sdk/client-bedrock-runtime";
import { ChatBedrockConverse } from "@langchain/aws";
import { FetchHttpHandler } from "@smithy/fetch-http-handler";
import http from "node:http";
import * as check from "./checks.js";

process.env.TZ = "America/Sao_Paulo"; // CI runs in UTC, where a signing time read as local time would pass unseen
const sdk = await check.load();
const BEDROCK = "bedrock-runtime.us-east-1.amazonaws.com";
const ELSEWHERE = "elsewhere.example";
const BEARER = "ABSKbWFkZS11cC1iZWRyb2NrLWtleQ=="; // a Bedrock API key's form, made up
const CREDENTIALS = { accessKeyId: "AKIDMADEUPEXAMPLE", secretAccessKey: "made-up-secret" };
const MODEL = "anthropic.frontier-b-v1:0";
const HI = [{ role: "user", content: [{ text: "Hi" }] }];
const INVOKE = JSON.stringify({ anthropic_version: "bedrock-2023-05-31", max_tokens: 8, messages: [{ role: "user", content: "Hi" }] });
const FROM = { reflexer: "from reflexer", bedrock: "from bedrock" };
const WINDOW = 300_000; // ms a signature holds at Bedrock from its signing time: AWS's five minutes
const clock = { offset: 0 }; // ms Bedrock's clock is ahead of this machine's, in a case that moves it

/**
 * Why Bedrock refuses a SigV4 request, or null: its scope this endpoint's own region and service, its signature
 * recomputed by Smithy's own signer over the headers it says
 * it signed, at the time it says it signed, with the made-up secret, and that time within the window of Bedrock's clock.
 * @param {URL} url @param {Headers} headers @param {string} body
 */
async function refusal(url, headers, body, raw = (/** @type {string} */ name) => headers.get(name)) {
  const auth = headers.get("authorization") ?? "";
  if (!auth.startsWith("AWS4-HMAC-SHA256 ")) return null;
  const parts = Object.fromEntries(auth.slice(17).split(",").map((part) => part.trim().split("=")));
  const [, , region, service] = parts.Credential.split("/");
  if (url.hostname !== BEDROCK || region !== "us-east-1" || service !== "bedrock") return "the scope is not this endpoint's"; // Bedrock's own, not the one the call names
  const date = headers.get("x-amz-date") ?? "";
  const at = Date.parse(date.replace(/^(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)Z$/, "$1-$2-$3T$4:$5:$6Z"));
  const signedHeaders = Object.fromEntries(parts.SignedHeaders.split(";").map((name) => [name, raw(name) ?? (name === "host" ? url.host : "")]));
  const request = new HttpRequest({ method: "POST", protocol: url.protocol, hostname: url.hostname, path: url.pathname,
    query: Object.fromEntries(url.searchParams), headers: Object.fromEntries(Object.entries(signedHeaders).filter(([name]) => name !== "x-amz-date")), body });
  const signer = new SignatureV4({ credentials: CREDENTIALS, region, service, sha256: Sha256, uriEscapePath: true, applyChecksum: false });
  const again = await signer.sign(request, { signingDate: at / 1000 });
  if (again.headers.authorization?.split("Signature=")[1] !== parts.Signature) return "the signature does not match";
  if (Math.abs(Date.now() + clock.offset - at) > WINDOW) return "Signature expired";
  return null;
}

// The AI SDK's Bedrock provider's own floor of Node, above this package's
const engines = JSON.parse(readFileSync(new URL("../node_modules/@ai-sdk/amazon-bedrock/package.json", import.meta.url), "utf8")).engines.node;
const tooOld = Number(process.versions.node.split(".")[0]) < Number(/\d+/.exec(engines)?.[0]) && `the AI SDK's Bedrock provider needs Node ${engines}`;
const ai = tooOld ? null : { ...(await import("@ai-sdk/amazon-bedrock")), ...(await import("ai")) };

// ---- Bedrock's wire, as AWS answers: JSON, or its binary event stream

const CRC = Array.from({ length: 256 }, (_, n) => {
  for (let bit = 0; bit < 8; bit++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1;
  return n >>> 0;
});
/** @param {Uint8Array} bytes */
const crc32 = (bytes) => (bytes.reduce((crc, byte) => CRC[(crc ^ byte) & 0xff] ^ (crc >>> 8), 0xffffffff) ^ 0xffffffff) >>> 0;

/** One message of AWS's event stream: its prelude, string headers, a JSON payload, each part's CRC. @param {string} type @param {object} body */
function frame(type, body) {
  const text = new TextEncoder();
  const headers = Buffer.concat(Object.entries({ ":event-type": type, ":message-type": "event", ":content-type": "application/json" })
    .map(([name, value]) => Buffer.concat([Buffer.from([name.length]), text.encode(name), Buffer.from([7, 0, value.length]), text.encode(value)])));
  const payload = text.encode(JSON.stringify(body));
  const message = Buffer.alloc(16 + headers.length + payload.length);
  message.writeUInt32BE(message.length, 0);
  message.writeUInt32BE(headers.length, 4);
  message.writeUInt32BE(crc32(message.subarray(0, 8)), 8);
  headers.copy(message, 12);
  Buffer.from(payload).copy(message, 12 + headers.length);
  message.writeUInt32BE(crc32(message.subarray(0, message.length - 4)), message.length - 4);
  return message;
}

/** Each Bedrock call's answer, of its operation's form: (content type, body). @param {string} path @param {string} text */
function answer(path, text) {
  const op = path.split("/").pop();
  const usage = { inputTokens: 3, outputTokens: 1, totalTokens: 4 };
  if (op === "converse") {
    return ["application/json", JSON.stringify({ output: { message: { role: "assistant", content: [{ text }] } }, stopReason: "end_turn", usage,
      metrics: { latencyMs: 1 } })];
  }
  if (op === "converse-stream") {
    return ["application/vnd.amazon.eventstream", Buffer.concat([frame("messageStart", { role: "assistant" }),
      frame("contentBlockDelta", { contentBlockIndex: 0, delta: { text } }), frame("contentBlockStop", { contentBlockIndex: 0 }),
      frame("messageStop", { stopReason: "end_turn" }), frame("metadata", { usage, metrics: { latencyMs: 1 } })])];
  }
  const message = { id: "msg-made-up", type: "message", role: "assistant", model: MODEL, content: [{ type: "text", text }], stop_reason: "end_turn",
    stop_sequence: null, usage: { input_tokens: 3, output_tokens: 1 } };
  if (op === "invoke") return ["application/json", JSON.stringify(message)];
  if (op === "invoke-with-response-stream") {
    const events = [{ type: "message_start", message: { ...message, content: [], stop_reason: null } },
      { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
      { type: "content_block_delta", index: 0, delta: { type: "text_delta", text } }, { type: "content_block_stop", index: 0 },
      { type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { output_tokens: 1 } }, { type: "message_stop" }];
    return ["application/vnd.amazon.eventstream", Buffer.concat(events.map((event) =>
      frame("chunk", { bytes: Buffer.from(JSON.stringify(event)).toString("base64") })))];
  }
  return ["application/json", JSON.stringify({ inputTokens: 3 })]; // count-tokens
}

/** A request's body, as text. @param {any} body */
const bodyText = (body) => (body == null ? "" : typeof body === "string" ? body : new TextDecoder().decode(body));

const OURS = { "reflexer-status-origin": "reflexer", "reflexer-answered-by": "reflexer" };
const LATE = 1100; // ms a "late" reflexer takes to answer busy: past x-amz-date's one-second step

/**
 * How the far ends answer, by host: (status, headers, body) or a failure. `reflexer`: "served", "busy", "down",
 * "redirect" or "stall" (its answer never starts, until the call is cut).
 * @param {string} reflexer @param {URL} url @param {AbortSignal | null | undefined} signal
 */
async function far(reflexer, url, signal, bedrock = "ok", headers = new Headers(), sent = "", raw = undefined) {
  const ours = url.host === check.REFLEXER;
  const mode = ours ? reflexer : bedrock;
  if (mode === "down") throw new TypeError("fetch failed");
  if (mode === "late") await new Promise((done) => setTimeout(done, LATE)); // then busy: a leg that took its time
  const refused = ours ? null : await refusal(url, headers, sent, raw);
  if (refused) return { status: 403, headers: { "content-type": "application/json", "x-amzn-errortype": "InvalidSignatureException" }, body: JSON.stringify({ message: refused }) };
  if (mode === "stall") {
    await check.stalled(signal);
  }
  if (mode === "busy" || mode === "late") return { status: 503, headers: { "reflexer-status-origin": "reflexer", "content-type": "application/json" }, body: "{}" };
  if (mode === "redirect") return { status: 307, headers: { location: `https://${ELSEWHERE}/moved`, "reflexer-status-origin": "reflexer" }, body: "" };
  const [type, body] = answer(url.pathname, ours ? FROM.reflexer : FROM.bedrock);
  return { status: 200, headers: { "content-type": type, ...(ours ? OURS : {}) }, body };
}

/**
 * A client's own `fetch` on those far ends; every request it received, in `seen`. It follows redirects as `fetch` does.
 * @param {string} reflexer
 */
function fetchOn(reflexer, bedrock = "ok") {
  /** @type {{ url: URL, headers: Headers, body: string, init: any }[]} */
  const seen = [];
  /** @param {any} input @param {any} init @returns {Promise<Response>} */
  const fetch = async (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : input);
    init.signal?.throwIfAborted();
    seen.push({ url, headers: new Headers(init.headers), body: bodyText(init.body), init });
    const { status, headers, body } = await far(reflexer, url, init.signal, bedrock, new Headers(init.headers), bodyText(init.body));
    if (headers.location && init.redirect !== "manual") return fetch(headers.location, init);
    return new Response(status === 307 || status === 503 ? null : body, { status, headers });
  };
  return { fetch, seen };
}

/** A client's own AWS JS request handler on those far ends, as Smithy's own: it follows no redirect. @param {string} reflexer */
function handlerOn(reflexer, bedrock = "ok") {
  /** @type {{ url: URL, headers: Headers, body: string, request: any }[]} */
  const seen = [];
  const handler = {
    metadata: { handlerProtocol: "h2" },
    /** @param {any} request @param {any} [options] */
    async handle(request, options = {}) {
      const url = new URL(`${request.protocol}//${request.hostname}${request.port ? `:${request.port}` : ""}${request.path}`);
      options.abortSignal?.throwIfAborted?.();
      const given = new Headers(Object.entries(request.headers).filter(([name]) => !name.startsWith(":")));
      seen.push({ url, headers: given, body: bodyText(request.body), request: structuredClone({ ...request, body: bodyText(request.body) }) });
      const raw = (/** @type {string} */ name) => Object.entries(request.headers).find(([each]) => each.toLowerCase() === name)?.[1];
      const { status, headers, body } = await far(reflexer, url, options.abortSignal, bedrock, given, bodyText(request.body), raw);
      return { response: { statusCode: status, headers, body: Readable.from([Buffer.from(body)]) } };
    },
    updateHttpClientConfig() {},
    httpHandlerConfigs: () => ({}),
  };
  return { handler, seen };
}

// ---- Each line, as a client writes it: keyed, or signed

/**
 * [name, its operations, make(own, keyed, options) -> call(op, extra)], each over the client's own fetch or handler.
 * `extra`: `{ headers, argument }`, the skip's forms where the line takes them.
 * @type {[string, string[], (way: any, keyed: boolean, options?: any) => (op: string, extra?: any) => Promise<string>][]}
 */
const LINES = [
  ["aws-js", ["converse", "converse-stream", "invoke", "invoke-with-response-stream"], (way, keyed, options = {}) => {
    const client = sdk.bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1", maxAttempts: 1, requestHandler: way.handler,
      ...(keyed ? { token: { token: BEARER }, authSchemePreference: ["httpBearerAuth"] } : { credentials: CREDENTIALS }) }), sdk.key, options);
    return (op, extra = {}) => awsCall(client, op, extra);
  }],
  ["langchain-js", ["converse"], (way, keyed, options = {}) => {
    const client = sdk.bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1", maxAttempts: 1, requestHandler: way.handler,
      ...(keyed ? { token: { token: BEARER }, authSchemePreference: ["httpBearerAuth"] } : { credentials: CREDENTIALS }) }), sdk.key, options);
    const chat = new ChatBedrockConverse({ model: MODEL, region: "us-east-1", maxRetries: 0, client });
    return async (_, extra = {}) => {
      const id = headerOnEachCall(client, extra.headers);
      try {
        return String((await chat.invoke("Hi")).content);
      } finally {
        if (id) client.middlewareStack.remove(id);
      }
    };
  }],
  ["anthropic-bedrock", ["invoke", "invoke-with-response-stream"], (way, keyed, options = {}) => {
    const client = new AnthropicBedrock({ awsRegion: "us-east-1", maxRetries: 0, ...options.client, fetch: sdk.bedrock.fetch(sdk.key, { ...options, fetch: way.fetch }),
      middleware: [sdk.bedrock.anthropicMiddleware], ...(keyed ? { apiKey: BEARER } : { awsAccessKey: CREDENTIALS.accessKeyId, awsSecretKey: CREDENTIALS.secretAccessKey }) });
    return async (op, extra = {}) => {
      const params = { model: MODEL, max_tokens: 8, messages: [{ role: "user", content: "Hi" }] };
      const given = { headers: extra.headers, signal: extra.signal };
      if (op === "invoke") return (await client.messages.create(params, given)).content.map((part) => /** @type {any} */ (part).text).join("");
      let text = "";
      for await (const event of await client.messages.create({ ...params, stream: true }, given)) {
        if (event.type === "content_block_delta" && event.delta.type === "text_delta") text += event.delta.text;
      }
      return text;
    };
  }],
  ...(ai ? [/** @type {const} */ (["ai-sdk", ["converse", "converse-stream"], (/** @type {any} */ way, /** @type {boolean} */ keyed, options = {}) => {
    const provider = ai.createAmazonBedrock({ region: "us-east-1", fetch: sdk.bedrockAi.fetch(sdk.key, { ...options, fetch: way.fetch }),
      ...(keyed ? { apiKey: BEARER } : CREDENTIALS) });
    const model = ai.wrapLanguageModel({ model: provider(MODEL), middleware: sdk.bedrockAi.middleware });
    return async (/** @type {string} */ op, /** @type {any} */ extra = {}) => {
      const params = { model, prompt: "Hi", maxRetries: 0, headers: extra.headers, abortSignal: extra.signal,
        ...(extra.argument ? { providerOptions: { reflexer: { passThrough: true } } } : {}) };
      if (op === "converse") return (await ai.generateText(params)).text;
      let failure = null;
      const result = ai.streamText({ ...params, onError: ({ error }) => { failure = error; } });
      let text = "";
      for await (const part of result.textStream) text += part;
      if (failure) throw failure;
      return text;
    };
  }])] : []),
];

/** A header on every call of an AWS JS client, as a client's own middleware sets one, before signing. @param {any} client @param {any} headers */
function headerOnEachCall(client, headers) {
  if (!headers) return null;
  client.middlewareStack.add((/** @type {any} */ next) => (/** @type {any} */ args) => {
    Object.assign(args.request.headers, headers);
    return next(args);
  }, { step: "build", name: "madeUpOneCall" });
  return "madeUpOneCall";
}

/** @param {any} client @param {string} op @param {any} extra */
async function awsCall(client, op, extra) {
  const id = headerOnEachCall(client, extra.headers);
  const options = extra.argument ? { reflexerPassThrough: true } : undefined;
  try {
    if (op === "converse") return (await client.send(new ConverseCommand({ modelId: MODEL, messages: HI }), options)).output.message.content[0].text;
    if (op === "converse-stream") {
      let text = "";
      for await (const event of (await client.send(new ConverseStreamCommand({ modelId: MODEL, messages: HI }), options)).stream) {
        text += event.contentBlockDelta?.delta?.text ?? "";
      }
      return text;
    }
    if (op === "invoke") {
      const out = await client.send(new InvokeModelCommand({ modelId: MODEL, body: INVOKE, contentType: "application/json" }), options);
      return JSON.parse(new TextDecoder().decode(out.body)).content[0].text;
    }
    if (op === "invoke-with-response-stream") {
      let text = "";
      const out = await client.send(new InvokeModelWithResponseStreamCommand({ modelId: MODEL, body: INVOKE, contentType: "application/json" }), options);
      for await (const event of out.body) {
        const data = event.chunk ? JSON.parse(new TextDecoder().decode(event.chunk.bytes)) : {};
        if (data.type === "content_block_delta") text += data.delta.text;
      }
      return text;
    }
    return `tokens ${(await client.send(new CountTokensCommand({ modelId: MODEL, input: { converse: { messages: HI } } }), options)).inputTokens}`;
  } finally {
    if (id) client.middlewareStack.remove(id);
  }
}

/** The far ends a line's own fetch or handler stands for: both, as one `way`. @param {string} reflexer */
function farEnds(reflexer, bedrock = "ok") {
  const own = fetchOn(reflexer, bedrock), handled = handlerOn(reflexer, bedrock);
  return { fetch: own.fetch, handler: handled.handler, seen: () => [...own.seen, ...handled.seen] };
}

/** One call of a line, as a client makes it: what it answered or raised, and every request the far ends saw. */
async function called(/** @type {any} */ make, /** @type {boolean} */ keyed, /** @type {string} */ op, reflexer = "served", extra = {}, options = {}, bedrock = "ok") {
  const way = farEnds(reflexer, bedrock);
  const call = make(way, keyed, options);
  let result;
  try {
    result = await call(op, extra);
  } catch (failure) {
    result = failure;
  }
  return { result, seen: way.seen() };
}

/** @param {{ url: URL }[]} seen */
const hosts = (seen) => [...new Set(seen.map(({ url }) => url.host))].sort();

/** Every host whose request carried `value` in some header, for each line, over a fallback, a failure and a redirect. */
async function hostsGiven(/** @type {(sdk: any) => string} */ value, /** @type {boolean} */ keyed, faulty = sdk) {
  /** @type {Record<string, string[]>} */
  const found = {};
  for (const [name, ops, make] of linesOf(faulty)) {
    const given = new Set();
    for (const reflexer of ["busy", "down", "redirect", "served"]) {
      const { seen } = await called(make, keyed, ops[0], reflexer);
      for (const { url, headers } of seen) if ([...headers.values()].some((each) => each.includes(value(faulty)))) given.add(url.host);
    }
    found[name] = [...given].sort();
  }
  return found;
}

/** LINES, made with `faulty`'s bedrock.js. @param {any} faulty */
function linesOf(faulty) {
  if (faulty === sdk) return LINES;
  return LINES.map(([name, ops, make]) => [name, ops, (/** @type {any} */ way, /** @type {boolean} */ keyed, options = {}) => {
    const real = [sdk.bedrock, sdk.bedrockAi];
    [sdk.bedrock, sdk.bedrockAi] = [faulty.bedrock, faulty.bedrockAi]; // the line, made with the faulty modules; its calls keep them
    try {
      return make(way, keyed, options);
    } finally {
      [sdk.bedrock, sdk.bedrockAi] = real;
    }
  }]);
}

/** Headers that differ between two calls of one signed client: its signing time, signature, call id. */
const NAMESPACE = { "reflexer-namespace": "made-up" }; // a header of the client's, signed: it stays, as signed
const VOLATILE = new Set(["authorization", "x-amz-date", "amz-sdk-invocation-id", "x-amz-content-sha256", "amz-sdk-request"]);

/**
 * What a signed call's fallback sent, reflexer busy, but its volatile headers, by each line and by its stock form, and
 * whether Bedrock took it; and how many requests reflexer saw.
 */
async function signedAsMade(faulty = sdk, headers = undefined) {
  /** @type {Record<string, { line: any, stock: any, reflexer: number, result: any }>} */
  const found = {};
  for (const [name, ops, make] of linesOf(faulty)) {
    const ours = await called(make, false, ops[0], "busy", { headers });
    const stock = await called(stockOf(name), false, ops[0], "served", { headers });
    const sent = (/** @type {any[]} */ seen) => seen.filter(({ url }) => url.host === BEDROCK).map(({ url, headers, body }) =>
      ({ url: url.href, body, headers: [...headers].filter(([header]) => !VOLATILE.has(header)), signed: /^AWS4-HMAC-SHA256 /.test(headers.get("authorization") ?? "") }));
    found[name] = { line: sent(ours.seen), stock: sent(stock.seen), reflexer: ours.seen.filter(({ url }) => url.host === check.REFLEXER).length,
      result: ours.result };
  }
  return found;
}

/** A line's stock form: the same client, with no line of reflexer's. @param {string} name */
function stockOf(name) {
  return (/** @type {any} */ way, /** @type {boolean} */ keyed) => {
    const real = [sdk.bedrock, sdk.bedrockAi];
    const fetch = (/** @type {any} */ _, /** @type {any} */ options) => options.fetch;
    sdk.bedrock = { ...real[0], wrap: (/** @type {any} */ client) => client, fetch,
      anthropicMiddleware: (/** @type {any} */ request, /** @type {any} */ next) => next(request) };
    sdk.bedrockAi = { ...real[1], fetch, middleware: {} };
    try {
      return /** @type {any} */ (LINES.find(([line]) => line === name))[2](way, keyed);
    } finally {
      [sdk.bedrock, sdk.bedrockAi] = real;
    }
  };
}

describe("Bedrock", () => {
  for (const [name, ops, make] of LINES) {
    for (const op of ops) {
      test(`${name}: a keyed ${op} call goes to reflexer, with the key and its upstream, and its answer back`, async () => {
        const { result, seen } = await called(make, true, op);
        assert.equal(result, FROM.reflexer);
        assert.deepEqual(hosts(seen), [check.REFLEXER]);
        const [arrival] = seen;
        assert.equal(decodeURIComponent(arrival.url.pathname), `/bedrock/model/${MODEL}/${op}`); // each library escapes the `:` its own way
        assert.equal(arrival.headers.get("reflexer-upstream"), `https://${BEDROCK}`);
        assert.equal(arrival.headers.get("authorization"), `Bearer ${BEARER}`);
        assert.equal(arrival.headers.get("reflexer-key"), sdk.key);
      });
    }

    for (const reflexer of ["busy", "down"]) {
      test(`${name}: reflexer ${reflexer}, a keyed call goes straight with its key`, async () => {
        const { result, seen } = await called(make, true, ops[0], reflexer);
        assert.equal(result, FROM.bedrock);
        const straight = seen.filter(({ url }) => url.host === BEDROCK);
        assert.equal(straight.length, 1);
        assert.equal(straight[0].headers.get("authorization"), `Bearer ${BEARER}`);
        assert.ok(![...straight[0].headers.keys()].some((header) => header.startsWith("reflexer-")));
      });
    }

    test(`${name}: a signed call goes to reflexer as signed, and its answer back`, async () => {
      const { result, seen } = await called(make, false, ops[0]);
      assert.equal(result, FROM.reflexer);
      assert.deepEqual(hosts(seen), [check.REFLEXER]);
      assert.match(seen[0].headers.get("authorization") ?? "", /^AWS4-HMAC-SHA256 /);
      assert.equal(seen[0].headers.get("reflexer-upstream"), `https://${BEDROCK}`);
    });

    for (const reflexer of ["busy", "down"]) {
      test(`${name}: reflexer ${reflexer}, a signed call goes straight, and Bedrock takes it`, async () => {
        const { result, seen } = await called(make, false, ops[0], reflexer);
        assert.equal(result, FROM.bedrock, String(result));
        assert.equal(seen.filter(({ url }) => url.host === BEDROCK).length, 1);
      });
    }

    test(`${name}: a signed call's fallback is signed after reflexer's leg, or within its window`, async () => {
      const { result, seen } = await called(make, false, ops[0], "late");
      assert.equal(result, FROM.bedrock, String(result));
      const [leg, straight] = [check.REFLEXER, BEDROCK].map((host) => /** @type {any} */ (seen.find(({ url }) => url.host === host)).headers.get("x-amz-date"));
      if (name === "ai-sdk") assert.equal(straight, leg); // its fallback reuses its signature: its window bounds the leg
      else assert.ok(straight > leg, `${leg} then ${straight}`);
    });

    test(`${name}: the skip's header sends a keyed call straight, and leaves for no one`, async () => {
      for (const keyed of [true, false]) {
        const { result, seen } = await called(make, keyed, ops[0], "served", { headers: { "Reflexer-Pass-Through": "1" } });
        assert.equal(result, FROM.bedrock, `keyed ${keyed}`);
        assert.deepEqual(hosts(seen), [BEDROCK]);
        assert.ok(!seen.some(({ headers }) => headers.has("reflexer-pass-through")));
      }
    });

    test(`${name}: a replay never reaches Bedrock`, async () => {
      for (const [keyed, reflexer] of [[true, "busy"], [true, "down"], [false, "busy"], [false, "down"]]) {
        const way = farEnds(String(reflexer));
        const replayed = await replay(name, way, Boolean(keyed));
        assert.ok(replayed instanceof Error, `keyed ${keyed}, reflexer ${reflexer}: ${replayed}`);
        assert.ok(!way.seen().some(({ url }) => url.host === BEDROCK), `keyed ${keyed}, reflexer ${reflexer}`);
      }
    });
  }

  test("aws-js: the skip as an argument of the call sends it straight", async () => {
    const { result, seen } = await called(LINES[0][2], true, "converse", "served", { argument: true });
    assert.equal(result, FROM.bedrock);
    assert.deepEqual(hosts(seen), [BEDROCK]);
  });

  test("aws-js: a count of tokens goes straight", async () => {
    const { result, seen } = await called(LINES[0][2], true, "count-tokens");
    assert.equal(result, "tokens 3");
    assert.deepEqual(hosts(seen), [BEDROCK]);
  });

  test("aws-js: a client given the line twice throws, rather than try reflexer twice on each call", () => {
    const client = sdk.bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1", requestHandler: farEnds("served").handler }), sdk.key);
    assert.throws(() => sdk.bedrock.wrap(client, sdk.key), /already sends its calls through reflexer/);
  });

  test("aws-js: the client's own middleware never sees the key", async () => {
    const way = farEnds("busy");
    const client = sdk.bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1", maxAttempts: 1, requestHandler: way.handler,
      token: { token: BEARER }, authSchemePreference: ["httpBearerAuth"] }), sdk.key);
    /** @type {boolean[]} */
    const keyed = [];
    for (const step of ["finalizeRequest", "deserialize"]) {
      client.middlewareStack.add((/** @type {any} */ next) => (/** @type {any} */ args) => {
        keyed.push("reflexer-key" in args.request.headers);
        return next(args);
      }, { step, priority: "low", name: `madeUp${step}` });
    }
    assert.equal(await awsCall(client, "converse", {}), FROM.bedrock);
    assert.deepEqual(keyed, [false, false]);
  });

  test("ai-sdk: the skip as the call's provider option sends it straight", { skip: tooOld }, async () => {
    const make = /** @type {any} */ (LINES.find(([name]) => name === "ai-sdk"))[2];
    const { result, seen } = await called(make, true, "converse", "served", { argument: true });
    assert.equal(result, FROM.bedrock);
    assert.deepEqual(hosts(seen), [BEDROCK]);
  });
});

/** A replay through each line: what it raised or answered. @param {string} name @param {any} way @param {boolean} keyed */
async function replay(name, way, keyed) {
  const field = { replay_response: { id: "made-up" } };
  try {
    if (name === "aws-js" || name === "langchain-js") {
      const client = sdk.bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1", maxAttempts: 1, requestHandler: way.handler,
        ...(keyed ? { token: { token: BEARER }, authSchemePreference: ["httpBearerAuth"] } : { credentials: CREDENTIALS }) }), sdk.key);
      return await client.send(new InvokeModelCommand({ modelId: MODEL, body: JSON.stringify({ ...JSON.parse(INVOKE), ...field }), contentType: "application/json" }));
    }
    if (name === "anthropic-bedrock") {
      const client = new AnthropicBedrock({ awsRegion: "us-east-1", maxRetries: 0, fetch: sdk.bedrock.fetch(sdk.key, { fetch: way.fetch }),
        middleware: [sdk.bedrock.anthropicMiddleware], ...(keyed ? { apiKey: BEARER } : { awsAccessKey: CREDENTIALS.accessKeyId, awsSecretKey: CREDENTIALS.secretAccessKey }) });
      return await client.messages.create(/** @type {any} */ ({ model: MODEL, max_tokens: 8, messages: [{ role: "user", content: "Hi" }], ...field }));
    }
    const fetch = sdk.bedrockAi.fetch(sdk.key, { fetch: way.fetch });
    const headers = { "content-type": "application/json", authorization: keyed ? `Bearer ${BEARER}` : "AWS4-HMAC-SHA256 Credential=made-up" };
    return await fetch(`https://${BEDROCK}/model/${MODEL}/converse`, { method: "POST", headers, body: JSON.stringify({ messages: HI, ...field }) });
  } catch (failure) {
    return failure;
  }
}

describe("Timeouts", () => {
  const anthropic = /** @type {any} */ (LINES.find(([name]) => name === "anthropic-bedrock"))[2];
  const TIMEOUT = 300; // ms, the client's own

  test("anthropic-bedrock: reflexer stalled past the client's timeout, the call goes straight with its timeout afresh", async () => {
    const began = performance.now();
    const { result, seen } = await called(anthropic, true, "invoke", "stall", {}, { client: { timeout: TIMEOUT } });
    assert.equal(result, FROM.bedrock);
    assert.deepEqual(hosts(seen), [check.REFLEXER, BEDROCK]);
    assert.ok(performance.now() - began < 3 * TIMEOUT, `took ${performance.now() - began}ms`);
  });

  test("anthropic-bedrock: the client's cancel during reflexer's leg is the client's, never sent straight", async () => {
    const signal = AbortSignal.timeout(TIMEOUT / 3); // a cancel of the client's, as its own signal
    const { result, seen } = await called(anthropic, true, "invoke", "stall", { signal }, { client: { timeout: 10 * TIMEOUT } });
    assert.ok(result instanceof Error, String(result));
    assert.deepEqual(hosts(seen), [check.REFLEXER]);
  });

  test("ai-sdk: reflexer stalled past the call's timeout, a call not streamed goes straight", { skip: tooOld }, async () => {
    const make = /** @type {any} */ (LINES.find(([name]) => name === "ai-sdk"))[2];
    const { result, seen } = await called(make, true, "converse", "stall", { signal: AbortSignal.timeout(TIMEOUT) });
    assert.equal(result, FROM.bedrock);
    assert.deepEqual(hosts(seen), [check.REFLEXER, BEDROCK]);
  });

  test("ai-sdk: after its timeout at reflexer, the straight leg ends at as long again", { skip: tooOld }, async () => {
    const make = /** @type {any} */ (LINES.find(([name]) => name === "ai-sdk"))[2];
    const began = performance.now();
    const { result, seen } = await called(make, true, "converse", "stall", { signal: AbortSignal.timeout(TIMEOUT) }, {}, "stall");
    const took = performance.now() - began;
    assert.ok(result instanceof Error, String(result));
    assert.deepEqual(hosts(seen), [check.REFLEXER, BEDROCK]);
    assert.ok(took >= 2 * TIMEOUT - 50 && took < 4 * TIMEOUT, `took ${took}ms`);
  });
});

/** Whether a call naming each release throws, by each line's way in: `fetch` and AWS JS's handler. @param {any} faulty */
async function untestedThrows(faulty, labels = UNTESTED, named = "user-agent") {
  /** @type {Record<string, boolean>} */
  const found = {};
  for (const label of labels) {
    const way = farEnds("served");
    const headers = { [named]: `made-up ${label}`, authorization: `Bearer ${BEARER}` };
    const body = JSON.stringify({ messages: HI });
    const viaFetch = faulty.bedrock.fetch(sdk.key, { fetch: way.fetch })(`https://${BEDROCK}/model/${MODEL}/converse`, { method: "POST", headers, body });
    const viaHandler = faulty.bedrock.requestHandler(sdk.key, { handler: way.handler }).handle({ method: "POST", protocol: "https:", hostname: BEDROCK,
      path: `/model/${MODEL}/converse`, query: {}, headers, body });
    const thrown = await Promise.all([viaFetch, viaHandler].map((made) => made.then(() => false, () => true)));
    found[label] = thrown.every(Boolean) && way.seen().length === 0;
  }
  return found;
}

// Releases not tested: a newer major, an older one, one below the floor, as each library's calls name them
const UNTESTED = ["api/bedrock-runtime#4.0.0", "api/bedrock-runtime#2.9.0", "api/bedrock-runtime#3.1.0", "ai-sdk-amazon-bedrock/6.0.0",
  "ai-sdk-amazon-bedrock/5.0.1", "AnthropicBedrock/JS 2.0.0", "AnthropicBedrock/JS 0.9.0"];

describe("Tested", () => {
  test("each line's calls name a release of a library tested", async () => {
    for (const [name, ops, make] of LINES) {
      const { seen } = await called(make, true, ops[0]);
      const label = seen[0].headers.get("user-agent") ?? "";
      const named = sdk.bedrock.LIBRARIES.filter((/** @type {any} */ library) => library.label.test(label));
      assert.equal(named.length, 1, `${name}: ${label}`);
    }
  });

  test("a release not tested throws, and nothing is sent", async () => {
    assert.ok(Object.values(await untestedThrows(sdk)).every(Boolean), JSON.stringify(await untestedThrows(sdk)));
  });

  test("a release not tested, named only where a browser's AWS JS names it, throws", async () => {
    const found = await untestedThrows(sdk, UNTESTED, "x-amz-user-agent"); // a browser sets no user-agent of its own
    assert.ok(Object.values(found).every(Boolean), JSON.stringify(found));
  });

  test("AnthropicBedrock's calls are named by this list, not by the provider SDKs' own", () => {
    assert.deepEqual(sdk.index.tested(new Headers({ "user-agent": "AnthropicBedrock/JS 2.0.0" })), []);
    assert.ok(sdk.bedrock.LIBRARIES.some((/** @type {any} */ library) => library.label.test("AnthropicBedrock/JS 2.0.0")));
  });
});

/**
 * AWS JS on Smithy's own FetchHttpHandler, its browser and edge runtimes' handler, wrapped, over real sockets on this
 * machine: reflexer answers a redirect to another origin. Whom the key reached, and whether the line was taken at all.
 * @param {any} lines the package, or a faulty copy
 */
async function onTheFetchHandler(lines) {
  /** @type {string[]} */
  const keyed = [];
  const listen = (/** @type {any} */ handler) => new Promise((ok) => { const server = http.createServer(handler).listen(0, "127.0.0.1", () => ok(server)); });
  const elsewhere = /** @type {any} */ (await listen((/** @type {any} */ request, /** @type {any} */ response) => {
    if (request.headers["reflexer-key"]) keyed.push("elsewhere");
    response.writeHead(200, { "content-type": "application/json", "reflexer-status-origin": "reflexer" });
    response.end(answer(`/model/${MODEL}/converse`, FROM.reflexer).body);
  }));
  const reflexer = /** @type {any} */ (await listen((/** @type {any} */ request, /** @type {any} */ response) => {
    if (request.headers["reflexer-key"]) keyed.push("reflexer");
    request.resume();
    response.writeHead(307, { location: `http://127.0.0.1:${elsewhere.address().port}/moved`, "reflexer-status-origin": "reflexer" });
    response.end();
  }));
  try {
    const client = lines.bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1", maxAttempts: 1, endpoint: "https://bedrock.made-up.invalid",
      token: { token: BEARER }, authSchemePreference: ["httpBearerAuth"], requestHandler: new FetchHttpHandler() }), sdk.key,
    { base: `http://127.0.0.1:${reflexer.address().port}` });
    await client.send(new ConverseCommand({ modelId: MODEL, messages: HI })).catch(() => null);
    return { refused: false, keyed };
  } catch (failure) {
    return { refused: /do not follow redirects/.test(String(failure)), keyed };
  } finally {
    reflexer.close();
    elsewhere.close();
  }
}

/**
 * At each error the Bedrock lines throw to the client, the SDK's own frames' locals that show the reflexer key as an error
 * tracker capturing locals reads them: local, block and catch scopes, an object's own properties one level deep. The
 * scene runs in a process of its own under the inspector, watched over the DevTools protocol, which pauses on every
 * exception. Its errors, and where the key showed.
 * @param {any} lines the package, or a faulty copy
 */
const FRAMES_WITHIN_MS = 30000; // the frame check, its scene started to its result
const NEVER_WITHIN_MS = 2000; // the bound a scene that never answers is given, so its check is quick

async function framesAtThrows(lines, scene = new URL("./frames-scene.js", import.meta.url).pathname, within = FRAMES_WITHIN_MS) {
  const { spawn } = await import("node:child_process");
  const child = spawn(process.execPath, ["--inspect-brk=127.0.0.1:0", scene, lines.root], { stdio: ["ignore", "pipe", "pipe"] });
  let out = "", timer, socket, poll;
  child.stdout.on("data", (data) => { out += data; });
  const late = new Promise((_, fail) => { timer = setTimeout(() => fail(new Error(`no result within ${within} ms: ${out}`)), within); });
  const ended = new Promise((_, fail) => child.on("exit", (code) => fail(new Error(`the scene ended (${code}) before its result: ${out}`))));
  const watched = async () => {
    const url = await new Promise((ok) => child.stderr.on("data", (data) => { const found = /ws:\/\/\S+/.exec(String(data)); if (found) ok(found[0]); }));
    socket = new WebSocket(String(url));
    await new Promise((ok) => socket.addEventListener("open", ok));
    let id = 0;
    const waiting = new Map(), scripts = new Map(), shown = new Set();
    const post = (/** @type {string} */ method, params = {}) => new Promise((ok) => { waiting.set(++id, ok); socket.send(JSON.stringify({ id, method, params })); });
    const text = (/** @type {any} */ value) => (value?.value !== undefined ? String(value.value) : value?.description ?? "");
    socket.addEventListener("message", async ({ data }) => {
      const message = JSON.parse(String(data));
      if (message.id) return waiting.get(message.id)?.(message.result ?? {});
      if (message.method === "Debugger.scriptParsed") return scripts.set(message.params.scriptId, message.params.url);
      if (message.method !== "Debugger.paused") return;
      for (const frame of message.params.callFrames.filter((/** @type {any} */ f) => (scripts.get(f.location.scriptId) ?? "").includes("/src/"))) {
        for (const scope of frame.scopeChain.filter((/** @type {any} */ s) => ["local", "block", "catch"].includes(s.type))) {
          for (const { name, value } of (await post("Runtime.getProperties", { objectId: scope.object.objectId, ownProperties: true })).result ?? []) {
            const inside = value?.objectId ? ((await post("Runtime.getProperties", { objectId: value.objectId, ownProperties: true })).result ?? []) : [];
            if ([text(value), ...inside.map((/** @type {any} */ p) => text(p.value))].some((each) => each.includes(lines.key))) {
              shown.add(`${frame.functionName || "(anonymous)"}.${name}`);
            }
          }
        }
      }
      socket.send(JSON.stringify({ id: ++id, method: "Debugger.resume", params: {} }));
    });
    await post("Debugger.enable");
    await post("Debugger.setPauseOnExceptions", { state: "all" });
    await post("Runtime.runIfWaitingForDebugger");
    await new Promise((ok) => { poll = setInterval(() => { if (out.includes("thrown")) ok(null); }, 20); });
    return { thrown: JSON.parse(out).thrown, shown: [...shown].sort() };
  };
  try {
    return await Promise.race([watched(), late, ended]);
  } finally {
    clearTimeout(timer);
    clearInterval(poll);
    socket?.close();
    child.kill(); // the inspector holds it, waiting for its debugger to leave
  }
}

const noSocket = typeof WebSocket === "undefined" && "Node 20 has no WebSocket client, which the DevTools protocol needs (Node 22's has)";

describe("Promises", () => {
  test("an error thrown to the client shows the key in no frame of the SDK's", { skip: noSocket }, async () => {
    assert.deepEqual(await framesAtThrows(sdk), { thrown: ["ReplayNotTaken", "ReplayNotTaken"], shown: [] });
  });

  test("aws-js on a handler that follows redirects is refused as the line is made", async () => {
    assert.deepEqual(await onTheFetchHandler(sdk), { refused: true, keyed: [] });
  });

  test("through each Bedrock line the key reaches only reflexer", async () => {
    for (const keyed of [true, false]) {
      for (const [name, given] of Object.entries(await hostsGiven((one) => one.key, keyed))) {
        assert.deepEqual(given, [check.REFLEXER], `${name}, keyed ${keyed}`);
      }
    }
  });

  test("a Bedrock API key or a signature reaches only Bedrock or reflexer, and the AWS secret no one", async () => {
    for (const keyed of [true, false]) {
      for (const [name, given] of Object.entries(await hostsGiven(() => (keyed ? BEARER : "AWS4-HMAC-SHA256 "), keyed))) {
        assert.deepEqual(given, [check.REFLEXER, BEDROCK].sort(), `${name}, keyed ${keyed}`);
      }
      for (const [name, given] of Object.entries(await hostsGiven(() => CREDENTIALS.secretAccessKey, keyed))) assert.deepEqual(given, [], name);
    }
  });

  test("a signed call goes to reflexer, and its fallback reaches the client's own fetch or handler as a stock call, taken", async () => {
    for (const headers of [undefined, NAMESPACE]) {
      for (const [name, { line, stock, reflexer, result }] of Object.entries(await signedAsMade(sdk, headers))) {
        assert.equal(reflexer, headers && name === "ai-sdk" ? 0 : 1, name); // the AI SDK signs a header of ours, and its fallback drops it: straight
        assert.equal(result, FROM.bedrock, `${name}: ${result}`);
        assert.ok(line.length === 1 && line[0].signed, name);
        assert.deepEqual(line, stock, name);
      }
    }
  });

  test("aws-js: the fallback is signed at the client's own clock, as AWS JS corrects it", async () => {
    assert.deepEqual(await clockHeld(sdk), { fallback: FROM.bedrock, reflexer: 1 });
  });
});

/**
 * An AWS JS client whose clock AWS JS corrected (Bedrock's clock ahead of this machine's by more than the window), its
 * signed call's fallback after a busy reflexer: what it answered, and how many requests reflexer saw.
 * @param {any} faulty
 */
async function clockHeld(faulty) {
  clock.offset = 2 * WINDOW;
  try {
    const way = farEnds("busy");
    const client = faulty.bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1", maxAttempts: 1, requestHandler: way.handler, credentials: CREDENTIALS }), sdk.key);
    client.config.systemClockOffset = clock.offset; // as AWS JS sets it from an answer's `Date`
    const fallback = await awsCall(client, "converse", {}).catch((/** @type {any} */ failure) => String(failure));
    return { fallback, reflexer: way.seen().filter(({ url }) => url.host === check.REFLEXER).length };
  } finally {
    clock.offset = 0;
  }
}

describe("Attempts", () => {
  test("anthropic-bedrock: a signed call never sent to reflexer is attempted once, its headers as signed", async () => {
    for (const headers of [undefined, NAMESPACE]) {
      const way = farEnds("served");
      let attempts = 0;
      const client = new AnthropicBedrock({ awsRegion: "us-east-1", maxRetries: 0, awsAccessKey: CREDENTIALS.accessKeyId, awsSecretKey: CREDENTIALS.secretAccessKey,
        fetch: sdk.bedrock.fetch(sdk.key, { fetch: way.fetch, sample: 0 }),
        middleware: [sdk.bedrock.anthropicMiddleware, (/** @type {any} */ request, /** @type {any} */ next) => { attempts += 1; return next(request); }] });
      const answer = await client.messages.create({ model: MODEL, max_tokens: 8, messages: [{ role: "user", content: "Hi" }] }, { headers });
      assert.equal(answer.content.map((/** @type {any} */ part) => part.text).join(""), FROM.bedrock);
      assert.equal(attempts, 1, JSON.stringify(headers));
      assert.deepEqual(hosts(way.seen()), [BEDROCK]);
    }
  });
});

describe("Window", { skip: tooOld }, () => {
  const make = /** @type {any} */ (LINES.find(([name]) => name === "ai-sdk"))[2];

  test("ai-sdk: reflexer stalled, its leg is cut while the signature holds, and the same signed call goes straight", async () => {
    assert.ok(await windowCuts(sdk));
  });

  test("ai-sdk: a signed call with no time left of its window goes straight, never to reflexer", async () => {
    const { margin } = sdk.bedrockAi.WINDOW;
    sdk.bedrockAi.WINDOW.margin = sdk.bedrockAi.WINDOW.ms + 1;
    try {
      const { result, seen } = await called(make, false, "converse");
      assert.equal(result, FROM.bedrock);
      assert.deepEqual(hosts(seen), [BEDROCK]);
    } finally {
      sdk.bedrockAi.WINDOW.margin = margin;
    }
  });
});

/** Whether the AI SDK's signed call, reflexer stalled, its window shortened, went straight within it. @param {any} faulty */
async function windowCuts(faulty) {
  const make = /** @type {any} */ (linesOf(faulty).find(([name]) => name === "ai-sdk"))[2];
  const { ms, margin } = faulty.bedrockAi.WINDOW;
  Object.assign(faulty.bedrockAi.WINDOW, { ms: 1500, margin: 500 }); // the leg may take a second
  const began = performance.now();
  try {
    const { result, seen } = await called(make, false, "converse", "stall", { signal: AbortSignal.timeout(3000) });
    return result === FROM.bedrock && performance.now() - began < 1500 && hosts(seen).length === 2;
  } finally {
    Object.assign(faulty.bedrockAi.WINDOW, { ms, margin });
  }
}

describe("Broken", () => {
  test("the key on the client's own request turns it red", async () => {
    await check.planted("bedrock.js", ": smithyStaysStraight(request), given);\n    },",
      ": { ...smithyStaysStraight(request), headers: { ...request.headers, \"reflexer-key\": key } }, given);\n    },",
      async (faulty) => {
        const given = await hostsGiven((one) => one.key, true, faulty);
        assert.ok(given["aws-js"].includes(BEDROCK), JSON.stringify(given));
      });
    await check.planted("bedrock.js", "const own = (/** @type {any} */ input, /** @type {any} */ init) => (options.fetch ?? globalThis.fetch)(input, init);",
      "const own = (/** @type {any} */ input, /** @type {any} */ init) => (options.fetch ?? globalThis.fetch)(input, { ...init, headers: { ...Object.fromEntries(new Headers(init.headers)), \"reflexer-key\": key } });",
      async (faulty) => {
        const given = await hostsGiven((one) => one.key, true, faulty);
        assert.ok(given["anthropic-bedrock"].includes(BEDROCK), JSON.stringify(given));
      });
  });

  test("a redirect followed from reflexer turns it red", async () => {
    await check.planted("index.js", ', redirect: "manual" }', " }", async (faulty) => {
      assert.ok((await hostsGiven((one) => one.key, true, faulty))["anthropic-bedrock"].includes(ELSEWHERE));
      assert.ok((await hostsGiven(() => BEARER, true, faulty))["anthropic-bedrock"].includes(ELSEWHERE));
      assert.ok((await hostsGiven(() => "AWS4-HMAC-SHA256 ", false, faulty))["anthropic-bedrock"].includes(ELSEWHERE));
    });
  });

  test("a signed call not sent to reflexer turns it red", async () => {
    await check.planted("bedrock.js", "export const signed = (headers) => /^AWS4-HMAC-SHA256 /.test(headers.get(\"authorization\") ?? \"\");",
      "export const signed = (/** @type {Headers} */ headers) => false;", async (faulty) => {
        const found = await signedAsMade(faulty);
        assert.deepEqual(Object.values(found).map(({ reflexer }) => reflexer), Object.values(found).map(() => 0));
      });
  });

  test("the AWS secret sent turns it red", async () => {
    await check.planted("bedrock.js", "const route = reflexer.route(address.href, Object.fromEntries(new Headers(plain(request.headers))), isReplay(body));",
      "const route = reflexer.route(address.href, { ...Object.fromEntries(new Headers(plain(request.headers))), \"x-made-up\": \"made-up-secret\" }, isReplay(body));",
      async (faulty) => {
        assert.ok((await hostsGiven(() => CREDENTIALS.secretAccessKey, false, faulty))["aws-js"].includes(check.REFLEXER));
      });
  });

  test("a fallback not signed anew turns it red", async () => {
    await check.planted("bedrock.js", "sent && signed(headers) ? await signedAnew(signer, smithyStaysStraight(request))", "false ? null", async (faulty) => {
      const { result, seen } = await called(linesOf(faulty)[0][2], false, "converse", "late");
      const [leg, straight] = [check.REFLEXER, BEDROCK].map((host) => /** @type {any} */ (seen.find(({ url }) => url.host === host)).headers.get("x-amz-date"));
      assert.equal(straight, leg, String(result));
    });
    await check.planted("bedrock.js", "if (!again.straight || seen.cut) throw failure;", "throw failure;", async (faulty) => {
      const make = /** @type {any} */ (linesOf(faulty).find(([name]) => name === "anthropic-bedrock"))[2];
      const { result } = await called(make, false, "invoke", "busy");
      assert.ok(result instanceof Error, String(result));
    });
  });

  test("a fallback signed at the machine's clock, not AWS JS's own, turns it red", async () => {
    await check.planted("bedrock.js", "(Date.now() + (config.systemClockOffset ?? 0)) / 1000", "Date.now() / 1000", async (faulty) => {
      const { fallback } = await clockHeld(faulty);
      assert.notEqual(fallback, FROM.bedrock);
    });
  });

  test("a fallback signed for another scope turns it red", async () => {
    for (const scope of ['signingRegion: "eu-west-1"', 'signingService: "made-up-service"']) {
      await check.planted("bedrock.js", "{ signingDate: (Date.now() + (config.systemClockOffset ?? 0)) / 1000 }",
        `{ signingDate: (Date.now() + (config.systemClockOffset ?? 0)) / 1000, ${scope} }`, async (faulty) => {
          const { result } = await called(linesOf(faulty)[0][2], false, "converse", "busy");
          assert.notEqual(result, FROM.bedrock, scope);
        });
    }
  });

  test("ai-sdk: a leg not bounded by its window turns it red", { skip: tooOld }, async () => {
    await check.planted("bedrock-ai.js", "const time = String(input).startsWith(base) ? left(new Headers(init.headers)) : null;", "const time = null;", async (faulty) => {
      assert.equal(await windowCuts(faulty), false);
    });
  });

  test("ai-sdk: a signed header of ours sent to reflexer turns it red", { skip: tooOld }, async () => {
    await check.planted("bedrock-ai.js", "(time <= 0 || [...headers.keys()].some((name) => name.startsWith(OURS)))", "time <= 0", async (faulty) => {
      const { result } = (await signedAsMade(faulty, NAMESPACE))["ai-sdk"];
      assert.notEqual(result, FROM.bedrock);
    });
  });

  test("a handler that follows redirects taken turns it red", async () => {
    await check.planted("bedrock.js", "if (!FOLLOWS_NO_REDIRECT.includes(handler?.metadata?.handlerProtocol)) throw",
      "if (false) throw", async (faulty) => {
        // the check above, red: the line taken; on Node 22 and later, the key also reached the redirect's target (Node 20's fetch
        // followed no redirect of this call's in the run that showed it)
        assert.notDeepEqual(await onTheFetchHandler(faulty), { refused: true, keyed: [] });
      });
  });

  test("ai-sdk: a signing time read as local time turns it red", { skip: tooOld }, async () => {
    await check.planted("bedrock-ai.js", '"$1-$2-$3T$4:$5:$6Z"', '"$1-$2-$3T$4:$5:$6"', async (faulty) => {
      assert.equal(await windowCuts(faulty), false);
    });
  });

  test("a key in a frame of the SDK's at a throw turns it red", { skip: noSocket }, async () => {
    await check.planted("bedrock.js", "const { response, sent } = reflexerPassThrough ? { response: null, sent: false } : await ask(request, given);",
      "const held = { key }; const { response, sent } = reflexerPassThrough ? { response: null, sent: false } : await ask(request, given);", async (faulty) => {
        assert.deepEqual((await framesAtThrows(faulty)).shown, ["handle.held"]);
      });
  });

  test("a scene that never answers fails the frame check within its bound, never hangs it", { skip: noSocket, timeout: FRAMES_WITHIN_MS }, async () => {
    const { mkdtempSync, writeFileSync, rmSync } = await import("node:fs");
    const { tmpdir } = await import("node:os");
    const here = mkdtempSync(`${tmpdir()}/frames-`);
    try {
      writeFileSync(`${here}/never.js`, "setInterval(() => {}, 1000);\n"); // made up: a scene stuck before its result
      await assert.rejects(framesAtThrows({ ...sdk, key: "made-up" }, `${here}/never.js`, NEVER_WITHIN_MS), /no result within/);
    } finally {
      rmSync(here, { recursive: true });
    }
  });

  test("no version check turns it red", async () => {
    await check.planted("bedrock.js", "if (version && (", "if (false && (", async (faulty) => {
      assert.ok(Object.values(await untestedThrows(faulty)).every((thrown) => !thrown));
    });
  });

  test("a signed call's own headers taken off turns it red", async () => {
    await check.planted("bedrock.js", "const ours = keyed(new Headers(plain(request.headers))) ? OURS : PASS_THROUGH;", "const ours = OURS;", async (faulty) => {
      const found = await signedAsMade(faulty, NAMESPACE);
      assert.notDeepEqual(found["aws-js"].line, found["aws-js"].stock);
    });
  });
});

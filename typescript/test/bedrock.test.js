// Amazon Bedrock's lines, on their real libraries over a mock `fetch` or a mock request handler, offline; every value
// made up. A call with a Bedrock API key goes to reflexer; a call signed by SigV4 goes to Bedrock as its library made it.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Readable } from "node:stream";
import { describe, test } from "node:test";
import { AnthropicBedrock } from "@anthropic-ai/bedrock-sdk";
import { BedrockRuntimeClient, ConverseCommand, ConverseStreamCommand, CountTokensCommand, InvokeModelCommand,
  InvokeModelWithResponseStreamCommand } from "@aws-sdk/client-bedrock-runtime";
import { ChatBedrockConverse } from "@langchain/aws";
import * as check from "./checks.js";

const sdk = await check.load();
const BEDROCK = "bedrock-runtime.us-east-1.amazonaws.com";
const ELSEWHERE = "elsewhere.example";
const BEARER = "ABSKbWFkZS11cC1iZWRyb2NrLWtleQ=="; // a Bedrock API key's form, made up
const CREDENTIALS = { accessKeyId: "AKIDMADEUPEXAMPLE", secretAccessKey: "made-up-secret" };
const MODEL = "anthropic.frontier-b-v1:0";
const HI = [{ role: "user", content: [{ text: "Hi" }] }];
const INVOKE = JSON.stringify({ anthropic_version: "bedrock-2023-05-31", max_tokens: 8, messages: [{ role: "user", content: "Hi" }] });
const FROM = { reflexer: "from reflexer", bedrock: "from bedrock" };

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

/**
 * How the far ends answer, by host: (status, headers, body) or a failure. `reflexer`: "served", "busy", "down",
 * "redirect" or "stall" (its answer never starts, until the call is cut).
 * @param {string} reflexer @param {URL} url @param {AbortSignal | null | undefined} signal
 */
async function far(reflexer, url, signal, bedrock = "ok") {
  const ours = url.host === check.REFLEXER;
  const mode = ours ? reflexer : bedrock;
  if (mode === "down") throw new TypeError("fetch failed");
  if (mode === "stall") {
    await new Promise((_, fail) => signal?.addEventListener("abort", () => fail(signal.reason ?? new DOMException("aborted", "AbortError"))));
  }
  if (mode === "busy") return { status: 503, headers: { "reflexer-status-origin": "reflexer", "content-type": "application/json" }, body: "{}" };
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
    const { status, headers, body } = await far(reflexer, url, init.signal, bedrock);
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
      seen.push({ url, headers: new Headers(Object.entries(request.headers).filter(([name]) => !name.startsWith(":"))),
        body: bodyText(request.body), request: structuredClone({ ...request, body: bodyText(request.body) }) });
      const { status, headers, body } = await far(reflexer, url, options.abortSignal, bedrock);
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
    const provider = ai.createAmazonBedrock({ region: "us-east-1", fetch: sdk.bedrock.fetch(sdk.key, { ...options, fetch: way.fetch }),
      ...(keyed ? { apiKey: BEARER } : CREDENTIALS) });
    const model = ai.wrapLanguageModel({ model: provider(MODEL), middleware: sdk.bedrock.aiMiddleware });
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
    const real = sdk.bedrock;
    sdk.bedrock = faulty.bedrock; // the line, made with the faulty module; its calls keep it
    try {
      return make(way, keyed, options);
    } finally {
      sdk.bedrock = real;
    }
  }]);
}

/** Headers that differ between two calls of one signed client: its signing time, signature, call id. */
const VOLATILE = new Set(["authorization", "x-amz-date", "amz-sdk-invocation-id", "x-amz-content-sha256"]);

/** What a signed call sent, but its volatile headers, by each line and by its stock form; reflexer must see none. */
async function signedAsMade(faulty = sdk) {
  /** @type {Record<string, { line: any, stock: any, reflexer: number }>} */
  const found = {};
  const namespace = { "reflexer-namespace": "made-up" }; // a header of the client's, signed: it stays, as signed
  for (const [name, ops, make] of linesOf(faulty)) {
    const ours = await called(make, false, ops[0], "served", { headers: namespace });
    const stock = await called(stockOf(name), false, ops[0], "served", { headers: namespace });
    const sent = (/** @type {any[]} */ seen) => seen.filter(({ url }) => url.host === BEDROCK).map(({ url, headers, body }) =>
      ({ url: url.href, body, headers: [...headers].filter(([header]) => !VOLATILE.has(header)), signed: /^AWS4-HMAC-SHA256 /.test(headers.get("authorization") ?? "") }));
    found[name] = { line: sent(ours.seen), stock: sent(stock.seen), reflexer: ours.seen.filter(({ url }) => url.host === check.REFLEXER).length };
  }
  return found;
}

/** A line's stock form: the same client, with no line of reflexer's. @param {string} name */
function stockOf(name) {
  return (/** @type {any} */ way, /** @type {boolean} */ keyed) => {
    const real = sdk.bedrock;
    const none = { ...real, wrap: (/** @type {any} */ client) => client, fetch: (/** @type {any} */ _, /** @type {any} */ options) => options.fetch,
      anthropicMiddleware: (/** @type {any} */ request, /** @type {any} */ next) => next(request), aiMiddleware: {} };
    sdk.bedrock = none;
    try {
      return /** @type {any} */ (LINES.find(([line]) => line === name))[2](way, keyed);
    } finally {
      sdk.bedrock = real;
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

    test(`${name}: a signed call goes straight, never to reflexer`, async () => {
      const { result, seen } = await called(make, false, ops[0]);
      assert.equal(result, FROM.bedrock);
      assert.deepEqual(hosts(seen), [BEDROCK]);
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
      for (const [keyed, reflexer] of [[true, "busy"], [true, "down"], [false, "served"]]) {
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
    assert.throws(() => sdk.bedrock.wrap(client, sdk.key), /already sends through reflexer/);
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
    const fetch = sdk.bedrock.fetch(sdk.key, { fetch: way.fetch });
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
async function untestedThrows(faulty, labels = UNTESTED) {
  /** @type {Record<string, boolean>} */
  const found = {};
  for (const label of labels) {
    const way = farEnds("served");
    const headers = { "user-agent": `made-up ${label}`, authorization: `Bearer ${BEARER}` };
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

  test("AnthropicBedrock's calls are named by this list, not by the provider SDKs' own", () => {
    assert.deepEqual(sdk.index.tested(new Headers({ "user-agent": "AnthropicBedrock/JS 2.0.0" })), []);
    assert.ok(sdk.bedrock.LIBRARIES.some((/** @type {any} */ library) => library.label.test("AnthropicBedrock/JS 2.0.0")));
  });
});

describe("Promises", () => {
  test("through each Bedrock line the key reaches only reflexer", async () => {
    for (const keyed of [true, false]) {
      for (const [name, given] of Object.entries(await hostsGiven((one) => one.key, keyed))) {
        assert.deepEqual(given, keyed ? [check.REFLEXER] : [], `${name}, keyed ${keyed}`);
      }
    }
  });

  test("a Bedrock API key reaches only Bedrock or reflexer, and a signature only Bedrock", async () => {
    for (const [name, given] of Object.entries(await hostsGiven(() => BEARER, true))) {
      assert.deepEqual(given, [check.REFLEXER, BEDROCK].sort(), name);
    }
    for (const [name, given] of Object.entries(await hostsGiven(() => "AWS4-HMAC-SHA256 ", false))) {
      assert.deepEqual(given, [BEDROCK], name);
    }
  });

  test("a signed call never goes to reflexer, and reaches the client's own fetch or handler as its library made it", async () => {
    for (const [name, { line, stock, reflexer }] of Object.entries(await signedAsMade())) {
      assert.equal(reflexer, 0, name);
      assert.ok(line.length === 1 && line[0].signed, name);
      assert.deepEqual(line, stock, name);
    }
  });
});

describe("Broken", () => {
  test("the key on the client's own request turns it red", async () => {
    await check.planted("bedrock.js", "return handler.handle(smithyStaysStraight(request), given);\n    },",
      "return handler.handle({ ...smithyStaysStraight(request), headers: { ...request.headers, \"reflexer-key\": key } }, given);\n    },",
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
    });
  });

  test("a signed call sent to reflexer turns it red", async () => {
    await check.planted("bedrock.js", "if (!keyed(tested(new Headers(plain(request.headers))))) return", "if (false) return", async (faulty) => {
      assert.ok((await hostsGiven(() => "AWS4-HMAC-SHA256 ", false, faulty))["aws-js"].includes(check.REFLEXER));
      assert.ok((await signedAsMade(faulty))["aws-js"].reflexer > 0);
    });
    await check.planted("bedrock.js", "if (store?.skipped || !keyed(tested(new Headers(init.headers))))", "if (store?.skipped)", async (faulty) => {
      assert.ok((await hostsGiven(() => "AWS4-HMAC-SHA256 ", false, faulty))["anthropic-bedrock"].includes(check.REFLEXER));
      assert.ok((await signedAsMade(faulty))["anthropic-bedrock"].reflexer > 0);
    });
  });

  test("no version check turns it red", async () => {
    await check.planted("bedrock.js", "if (version && (", "if (false && (", async (faulty) => {
      assert.ok(Object.values(await untestedThrows(faulty)).every((thrown) => !thrown));
    });
  });

  test("a signed call's own headers taken off turns it red", async () => {
    await check.planted("bedrock.js", "const ours = keyed(new Headers(plain(request.headers))) ? OURS : PASS_THROUGH;", "const ours = OURS;", async (faulty) => {
      const found = await signedAsMade(faulty);
      assert.notDeepEqual(found["aws-js"].line, found["aws-js"].stock);
    });
    await check.planted("bedrock.js", "if (!keyed(headers)) return send(input, init);", "", async (faulty) => {
      const found = await signedAsMade(faulty);
      assert.notDeepEqual(found["anthropic-bedrock"].line, found["anthropic-bedrock"].stock);
    });
  });
});

// The `fetch` and the SDK lines, on a mock `fetch`, offline; every value made up.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { describe, test } from "node:test";
import * as check from "./checks.js";

const sdk = await check.load();
const { key, index } = sdk;
const STREAM = 'data: {"id":"made-up","object":"chat.completion.chunk","created":0,"model":"m","choices":[]}\n\ndata: [DONE]\n\n';

/** @param {check.Answer} answer */
function made(answer, options = {}) {
  const own = check.mock(answer);
  return { fetch: index.openai.fetch(key, { fetch: own.fetch, ...options }), seen: own.seen };
}

/** @param {check.Seen[]} seen */
const hosts = (seen) => seen.map(({ url }) => url.host);

describe("The wire", () => {
  test("an answer is the body as it came", async () => {
    const { fetch } = made(check.served);
    assert.deepEqual(await (await fetch(check.CHAT, { method: "POST", body: "{}" })).json(), { id: "made-up", from: "reflexer" });
  });

  test("a stream's bytes are the wire's, through the SDK too", async () => {
    const own = check.mock(() => new Response(STREAM, { headers: { "content-type": "text/event-stream", "reflexer-status-origin": "reflexer" } }));
    const raw = await index.openai.fetch(key, { fetch: own.fetch })(check.CHAT, { method: "POST", body: "{}" });
    assert.equal(await raw.text(), STREAM);
    const client = new sdk.openai.OpenAI({ apiKey: "made-up", reflexerKey: key, fetch: own.fetch });
    const chunks = [];
    for await (const chunk of await client.chat.completions.create({ model: "m", messages: [], stream: true })) chunks.push(chunk.id);
    assert.deepEqual(chunks, ["made-up"]);
    assert.deepEqual(new Set(hosts(own.seen)), new Set([check.REFLEXER]));
  });

  test("a body given as bytes goes to reflexer as a string does", async () => {
    const { fetch, seen } = made(check.served);
    await fetch(check.CHAT, { method: "POST", body: new TextEncoder().encode("{}") });
    assert.deepEqual(hosts(seen), [check.REFLEXER]);
  });
});

describe("Headers", () => {
  test("no header of ours leaves for the provider, and the pass-through header leaves for no one", async () => {
    const { fetch, seen } = made(check.served);
    const headers = { "reflexer-pass-through": "1", "reflexer-namespace": "made-up", "reflexer-made-up": "1", authorization: "Bearer sk-made-up" };
    await fetch(check.CHAT, { method: "POST", body: "{}", headers });
    assert.deepEqual(hosts(seen), ["api.openai.com"]);
    assert.deepEqual([...seen[0].headers.keys()], ["authorization"]);
  });

  test("the pass-through header, on one SDK call, sends it straight and leaves for no one", async () => {
    const own = check.mock(check.served);
    const client = new sdk.openai.OpenAI({ apiKey: "made-up", reflexerKey: key, fetch: own.fetch });
    await client.chat.completions.create({ model: "m", messages: [] }, { headers: { "Reflexer-Pass-Through": "1" } }).catch(() => {});
    assert.deepEqual(hosts(own.seen), ["api.openai.com"]);
    assert.ok(![...own.seen[0].headers.keys()].some((name) => name.startsWith("reflexer-")));
  });

  test("the namespace reaches reflexer", async () => {
    const { fetch, seen } = made(check.served);
    await fetch(check.CHAT, { method: "POST", body: "{}", headers: new Headers({ "reflexer-namespace": "made-up" }) });
    assert.equal(seen[0].headers.get("reflexer-namespace"), "made-up");
  });
});

describe("Straight", () => {
  test("a body that cannot be read twice goes straight, as given", async () => {
    const { fetch, seen } = made(check.served);
    const body = new ReadableStream({ start: (controller) => controller.close() });
    await fetch(check.CHAT, { method: "POST", body, duplex: "half", headers: { "reflexer-made-up": "1" } });
    assert.deepEqual(hosts(seen), ["api.openai.com"]);
    assert.equal(seen[0].init.body, body);
    assert.ok(!seen[0].headers.has("reflexer-made-up"));
  });

  test("a Request goes straight, keeping its own headers but ours", async () => {
    const { fetch, seen } = made(check.served);
    await fetch(new Request(check.CHAT, { method: "POST", body: "{}", headers: { authorization: "Bearer sk-made-up", "reflexer-made-up": "1" } }));
    assert.deepEqual(hosts(seen), ["api.openai.com"]);
    assert.equal(seen[0].headers.get("authorization"), "Bearer sk-made-up");
    assert.ok(!seen[0].headers.has("reflexer-made-up"));
  });

  test("a call that is no model's message goes straight", async () => {
    const { fetch, seen } = made(check.served);
    await fetch("https://api.openai.com/v1/models");
    assert.deepEqual(hosts(seen), ["api.openai.com"]);
  });

  test("a replay with the pass-through header throws, and nothing is sent", async () => {
    const { fetch, seen } = made(check.served);
    await assert.rejects(fetch(check.CHAT, { method: "POST", body: check.REPLAY, headers: { "reflexer-pass-through": "1" } }), index.ReplayNotTaken);
    assert.deepEqual(seen, []);
  });

  test("after a failure the next call goes straight, not trying reflexer", async (t) => {
    t.mock.method(console, "warn", () => {});
    const { fetch, seen } = made(check.down);
    await fetch(check.CHAT, { method: "POST", body: "{}" });
    await fetch(check.CHAT, { method: "POST", body: "{}" });
    assert.deepEqual(hosts(seen), [check.REFLEXER, "api.openai.com", "api.openai.com"]);
  });

  test("Reflexer-Straight is obeyed after two in a row", async () => {
    const told = () => new Response("{}", { headers: { "reflexer-status-origin": "reflexer", "reflexer-straight": "30" } });
    const { fetch, seen } = made(told);
    for (let n = 0; n < 3; n++) await fetch(check.CHAT, { method: "POST", body: "{}" });
    assert.deepEqual(hosts(seen), [check.REFLEXER, check.REFLEXER, "api.openai.com"]);
  });

  test("a share of the calls goes to reflexer", async () => {
    const { fetch, seen } = made(check.served, { sample: 0 });
    await fetch(check.CHAT, { method: "POST", body: "{}" });
    assert.deepEqual(hosts(seen), ["api.openai.com"]);
  });
});

describe("Own fetch", () => {
  test("with none given, the global one carries both legs", async (t) => {
    const own = check.mock(check.busy);
    t.mock.method(globalThis, "fetch", own.fetch);
    await index.openai.fetch(key)(check.CHAT, { method: "POST", body: "{}" });
    assert.deepEqual(hosts(own.seen), [check.REFLEXER, "api.openai.com"]);
  });

  test("an SDK's copy given its own fetch goes through reflexer the same way", async () => {
    for (const client of [new sdk.openai.OpenAI({ apiKey: "made-up", reflexerKey: key, maxRetries: 0 }),
      new sdk.anthropic.Anthropic({ apiKey: "made-up", reflexerKey: key, maxRetries: 0 })]) {
      const own = check.mock(check.served);
      const copy = /** @type {any} */ (client).withOptions({ fetch: own.fetch });
      await (copy.chat ? copy.chat.completions.create({ model: "m", messages: [] }) : copy.messages.create({ model: "m", max_tokens: 1, messages: [] }))
        .catch(() => {});
      assert.deepEqual(hosts(own.seen), [check.REFLEXER], client.constructor.name);
    }
  });

  test("the SDK's class keeps its name, which it puts in its user agent", () => {
    assert.equal(sdk.openai.OpenAI.name, "OpenAI");
    assert.equal(sdk.anthropic.Anthropic.name, "Anthropic");
  });

  test("a client made with no reflexer key throws", () => {
    assert.throws(() => new sdk.openai.OpenAI({ apiKey: "made-up" }), /not a reflexer key/);
    assert.throws(() => new sdk.gemini.GoogleGenAI(/** @type {any} */ ({ apiKey: "made-up" })), /not a reflexer key/);
  });
});

/** A server on this machine, answering by `answer`; its address. @param {import("node:http").RequestListener} answer */
async function serve(/** @type {any} */ t, answer) {
  const server = createServer(answer);
  await new Promise((done) => server.listen(0, "127.0.0.1", () => done(undefined)));
  t.after(() => server.close(() => {}) && server.closeAllConnections());
  return `http://127.0.0.1:${/** @type {import("node:net").AddressInfo} */ (server.address()).port}`;
}

/** `call`'s result, or a failure once `seconds` have passed. @param {Promise<any>} call */
const within = (call, seconds) => Promise.race([call, new Promise((_, reject) => setTimeout(() => reject(new Error("still waiting")), seconds * 1000).unref())]);

describe("Gemini's timeouts", () => {
  const DISPATCHER = Symbol.for("undici.globalDispatcher.1"); // where Node's fetch finds its global dispatcher

  /** What each leg's dispatcher hands Node's global one, with `make(fetch)` making the client on the global `fetch`. */
  async function dispatched(/** @type {any} */ t, /** @type {(fetch: any) => any} */ make) {
    const options = /** @type {any[]} */ ([]);
    new Headers(); // Node makes its global dispatcher on first use
    const real = /** @type {any} */ (globalThis)[DISPATCHER];
    assert.ok(real);
    /** @type {any} */ (globalThis)[DISPATCHER] = { dispatch: (/** @type {any} */ given) => options.push(given) };
    const own = check.mock(check.busy);
    const global = t.mock.method(globalThis, "fetch", (/** @type {any} */ input, /** @type {any} */ init) => {
      init?.dispatcher?.dispatch({ path: "/made-up" }, {});
      if (!init?.dispatcher) options.push("none");
      return own.fetch(input, init);
    });
    try {
      await make(own.fetch).models.generateContent({ model: "m", contents: "x" }).catch(() => {});
    } finally {
      global.mock.restore();
      /** @type {any} */ (globalThis)[DISPATCHER] = real;
    }
    return { options, hosts: hosts(own.seen) };
  }

  test("given no fetch, both legs go without undici's own timeouts, as stock google-genai's one does", async (t) => {
    const stock = await dispatched(t, () => new check.stock.GoogleGenAI({ apiKey: "made-up" }));
    const ours = await dispatched(t, () => new sdk.gemini.GoogleGenAI({ apiKey: "made-up", reflexerKey: key }));
    const byFetch = await dispatched(t, () => new check.stock.GoogleGenAI({ apiKey: "made-up", httpOptions: { fetch: index.gemini.fetch(key) } }));
    const untimed = { path: "/made-up", headersTimeout: 0, bodyTimeout: 0 };
    assert.deepEqual(stock.options, [untimed]);
    assert.deepEqual(ours, { options: [untimed, untimed], hosts: [check.REFLEXER, "generativelanguage.googleapis.com"] });
    assert.deepEqual(byFetch.options, [untimed, untimed]);
  });

  test("a fetch of the client's is left as given, as stock leaves it", async (t) => {
    const ours = await dispatched(t, (fetch) => new sdk.gemini.GoogleGenAI({ apiKey: "made-up", reflexerKey: key, httpOptions: { fetch } }));
    assert.deepEqual(ours.options, []); // the client's own fetch, not the global one, carried both legs
  });
});

describe("Failures", () => {
  test("on Gemini's defaults, a reflexer that takes the call and never answers is left at its headers timeout", async (t) => {
    t.mock.method(console, "warn", () => {});
    const stand = await serve(t, () => {}); // takes the call, answers nothing
    const real = globalThis.fetch, provider = check.mock(check.providers);
    const global = t.mock.method(globalThis, "fetch", (/** @type {any} */ input, /** @type {any} */ init) =>
      String(input).startsWith(stand) ? real(input, init) : provider.fetch(input, init));
    const routed = index.gemini.fetch(key, { base: stand, headersTimeout: 100 });
    const client = new check.stock.GoogleGenAI({ apiKey: "made-up", httpOptions: { fetch: routed } });
    try {
      const answer = await within(client.models.generateContent({ model: "m", contents: "x" }), 5);
      assert.equal(answer.responseId, "made-up");
      assert.deepEqual(hosts(provider.seen), ["generativelanguage.googleapis.com"]);
    } finally {
      global.mock.restore();
    }
  });

  test("the headers timeout bounds reflexer's leg only, not its answer once it came", async () => {
    const slow = check.mock((url) => check.served(url));
    const routed = index.openai.fetch(key, { fetch: slow.fetch, headersTimeout: 1 });
    const answer = await routed(check.CHAT, { method: "POST", body: "{}" });
    await new Promise((done) => setTimeout(done, 20));
    assert.deepEqual(await answer.json(), { id: "made-up", from: "reflexer" });
    assert.ok(!slow.seen[0].init.signal?.aborted);
  });

  test("an SDK's own timeout on a hung reflexer still reaches the provider, on its retry", async (t) => {
    t.mock.method(console, "warn", () => {});
    const seen = /** @type {string[]} */ ([]);
    const hung = (/** @type {any} */ input, /** @type {any} */ init) => {
      const url = new URL(input);
      seen.push(url.host);
      if (url.host !== check.REFLEXER) return Promise.resolve(check.providers(url));
      return new Promise((_, reject) => init.signal.addEventListener("abort", () => reject(init.signal.reason)));
    };
    const client = new sdk.openai.OpenAI({ apiKey: "made-up", reflexerKey: key, fetch: hung, timeout: 50, maxRetries: 1 });
    const answer = await client.chat.completions.create({ model: "m", messages: [] });
    assert.equal(/** @type {any} */ (answer).from, "provider");
    assert.deepEqual(seen, [check.REFLEXER, "api.openai.com"]);
  });
});

describe("Real sockets", () => {

  test("a redirect from reflexer is followed by neither fetch nor a dispatcher of the client's", async (t) => {
    const keyed = /** @type {string[]} */ ([]);
    const target = await serve(t, (request, response) => {
      if (request.headers["reflexer-key"]) keyed.push("the redirect's target");
      response.end("{}");
    });
    const stand = await serve(t, (_, response) => {
      response.writeHead(307, { location: `${target}/v1`, "reflexer-status-origin": "reflexer" }).end();
    });
    const asked = /** @type {unknown[]} */ ([]);
    const dispatcher = { // as undici's redirect interceptor reads it: no redirect followed when fetch asks for none
      dispatch: (/** @type {any} */ options, /** @type {any} */ handler) => {
        asked.push(options.maxRedirections);
        return /** @type {any} */ (globalThis)[Symbol.for("undici.globalDispatcher.1")].dispatch(options, handler);
      },
    };
    const provider = check.mock(check.providers);
    const own = (/** @type {any} */ input, /** @type {any} */ init) =>
      String(input).startsWith(stand) ? globalThis.fetch(input, init) : provider.fetch(input, init);
    const routed = index.openai.fetch(key, { base: stand, fetch: own });
    const answer = await routed(check.CHAT, { method: "POST", body: "{}", dispatcher });
    assert.equal((await answer.json()).from, "provider");
    assert.deepEqual(keyed, []);
    assert.deepEqual(asked, [0]);
  });
});

describe("Majors", () => {
  test("a version is supported on a tested major only", () => {
    index.supported("openai", "7.99.0");
    assert.throws(() => index.supported("openai", "8.0.0"), /tested on openai 7 from 7\.0\.0, not 8.0.0/);
  });

  test("a version below its SDK's tested floor throws, as an untested major does", () => {
    index.supported("@google/genai", "2.29.0");
    index.supported("@google/genai", "2.30.0");
    for (const version of ["2.28.0", "2.23.0", "2.9.9"]) assert.throws(() => index.supported("@google/genai", version), /tested on/, version);
  });

  test("a call that names a google-genai below its floor throws, and nothing is sent", async () => {
    const own = check.mock(check.served);
    const call = index.gemini.fetch(key, { fetch: own.fetch })("https://generativelanguage.googleapis.com/v1beta/models/m:generateContent",
      { method: "POST", body: "{}", headers: { "user-agent": "google-genai-sdk/2.28.0 gl-node/v24.0.0" } });
    await assert.rejects(call, /tested on @google\/genai 2 from 2\.29\.0, not 2\.28\.0/);
    assert.deepEqual(own.seen, []);
  });

  test("an untested major of openai or Anthropic throws at import", async () => {
    for (const [file, majors] of [["openai.js", 'name: "openai", majors: [7]'], ["anthropic.js", 'name: "@anthropic-ai/sdk", majors: [1]']]) {
      await check.planted("index.js", majors, majors.replace(/\[\d+\]/, "[0]"), async (faulty) => {
        assert.match(String(faulty[file.replace(".js", "")].failure), /tested on/, file);
      });
    }
  });

  test("an untested major throws on the stock class given reflexer's fetch too, and on the one line, never misroutes", async () => {
    for (const [name, majors] of [["openai", 'name: "openai", majors: [7]'], ["anthropic", 'name: "@anthropic-ai/sdk", majors: [1]'], ["gemini", 'name: "@google/genai", majors: [2]']]) {
      await check.planted("index.js", majors, majors.replace(/\[\d+\]/, "[0]"), async (faulty) => {
        for (const [line, call] of check.sdkCalls(faulty).filter(([line]) => line === `${name}, by fetch` || (name === "gemini" && line === name))) {
          const own = check.mock(check.served);
          await assert.rejects(call(own.fetch, {}), (/** @type {any} */ failure) => /tested on/.test(`${failure} ${failure.cause}`), line);
          assert.deepEqual(own.seen, [], line);
        }
      });
    }
  });

  test("on the one line, google-genai's major is read when the client sets its own user agent, and a call naming none throws", async () => {
    await check.planted("index.js", 'name: "@google/genai", majors: [2]', 'name: "@google/genai", majors: [0]', async (faulty) => {
      const own = check.mock(check.served);
      const client = new faulty.gemini.GoogleGenAI({ apiKey: "made-up", reflexerKey: faulty.key,
        httpOptions: { fetch: own.fetch, headers: { "User-Agent": "made-up-app/1.0" } } });
      await assert.rejects(client.models.generateContent({ model: "m", contents: "x" }), /tested on/);
      assert.deepEqual(own.seen, []);
    });
    const own = check.mock(check.served);
    const client = new sdk.gemini.GoogleGenAI({ apiKey: "made-up", reflexerKey: key,
      httpOptions: { fetch: own.fetch, headers: { "User-Agent": "made-up-app/1.0", "x-goog-api-client": "made-up-app/1.0" } } });
    await assert.rejects(client.models.generateContent({ model: "m", contents: "x" }), /cannot tell/);
    assert.deepEqual(own.seen, []);
  });

  test("LangChain's ChatAnthropic, on the Anthropic SDK's major 0, throws on reflexer's fetch, never misroutes", async () => {
    const own = check.mock(check.served);
    const chat = new check.stock.ChatAnthropic({ model: "m", apiKey: "made-up", maxRetries: 0,
      clientOptions: { fetch: index.anthropic.fetch(key, { fetch: own.fetch }) } });
    await assert.rejects(chat.invoke("x"), (/** @type {any} */ failure) => /tested on @anthropic-ai\/sdk 1/.test(`${failure} ${failure.cause}`));
    assert.deepEqual(own.seen, []);
  });

  test("a call through the fetch form that names no provider SDK goes as before", async () => {
    const { fetch, seen } = made(check.served);
    await fetch(check.CHAT, { method: "POST", body: "{}", headers: { "user-agent": "made-up-app/1.0" } });
    assert.deepEqual(hosts(seen), [check.REFLEXER]);
  });
});

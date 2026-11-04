// The `fetch` and the SDK lines, on a mock `fetch`, offline; every value made up.
import assert from "node:assert/strict";
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

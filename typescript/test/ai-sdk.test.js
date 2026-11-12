// The AI SDK's providers, given reflexer's `fetch` by their own `fetch` option: no code of reflexer's for them.
// On their real packages over a mock `fetch`, offline; every value made up.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";
import { createAnthropic } from "@ai-sdk/anthropic";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createOpenAI } from "@ai-sdk/openai";
import { generateText, streamText } from "ai";
import * as check from "./checks.js";

const { key, index } = await check.load();
const TIMEOUT = 150; // ms, the call's own
const USAGE = { input_tokens: 3, output_tokens: 1, total_tokens: 4, cost: 1.2e-05 };
const ANSWERS = {
  "/v1/chat/completions": { id: "rfx-made-up", object: "chat.completion", created: 1, model: "frontier-x-reflexer",
    choices: [{ index: 0, finish_reason: "stop", message: { role: "assistant", content: "made up" } }],
    usage: { prompt_tokens: 3, completion_tokens: 1, total_tokens: 4, cost: 1.2e-05 } },
  "/v1/responses": { id: "rfx-made-up", object: "response", created_at: 1, status: "completed", model: "frontier-x-reflexer",
    output: [{ type: "message", id: "msg-made-up", status: "completed", role: "assistant",
      content: [{ type: "output_text", text: "made up", annotations: [] }] }], usage: USAGE },
  "/v1/messages": { id: "rfx-made-up", type: "message", role: "assistant", model: "frontier-y-reflexer",
    content: [{ type: "text", text: "made up" }], stop_reason: "end_turn", stop_sequence: null, usage: USAGE },
  "/v1beta/models/frontier-z:generateContent": { responseId: "rfx-made-up", modelVersion: "frontier-z-reflexer",
    candidates: [{ content: { role: "model", parts: [{ text: "made up" }] }, finishReason: "STOP" }],
    usageMetadata: { promptTokenCount: 3, candidatesTokenCount: 1, totalTokenCount: 4 } },
};
const STREAM = [{ id: "rfx-made-up", object: "chat.completion.chunk", created: 1, model: "frontier-x-reflexer",
  choices: [{ index: 0, delta: { role: "assistant", content: "made up" }, finish_reason: "stop" }] }];

// The AI SDK's own floor of Node, above this package's: on an older Node it is not the AI SDK the client can have
const engines = JSON.parse(readFileSync(new URL("../node_modules/@ai-sdk/openai/package.json", import.meta.url), "utf8")).engines.node;
const tooOld = Number(process.versions.node.split(".")[0]) < Number(/\d+/.exec(engines)?.[0]) && `the AI SDK needs Node ${engines}`;

/** Each call of its form answered, by reflexer (its path under reflexer's) or by the provider; `busy`, reflexer's 503 that sends it straight. */
const answering = (busy = false) => (/** @type {URL} */ url) => {
  const ours = url.host === check.REFLEXER;
  if (ours && busy) return check.busy(url);
  const path = ours ? url.pathname.replace(/^\/[a-z]+/, "") : url.pathname;
  const headers = { "content-type": "application/json", ...(ours ? { "reflexer-status-origin": "reflexer", "reflexer-answered-by": "reflexer" } : {}) };
  return path in ANSWERS ? new Response(JSON.stringify(ANSWERS[/** @type {keyof ANSWERS} */ (path)]), { headers }) : new Response(null, { status: 404 });
};

/** [name, a model of the AI SDK's whose calls go by `fetch`, whether it names its model from the answer]. @type {[string, (fetch: any) => any, boolean][]} */
const MODELS = [
  ["openai chat", (fetch) => createOpenAI({ apiKey: "made-up", fetch: index.openai.fetch(key, { fetch }) }).chat("frontier-x"), true],
  ["openai responses", (fetch) => createOpenAI({ apiKey: "made-up", fetch: index.openai.fetch(key, { fetch }) }).responses("frontier-x"), true],
  ["anthropic", (fetch) => createAnthropic({ apiKey: "made-up", fetch: index.anthropic.fetch(key, { fetch }) })("frontier-y"), true],
  ["gemini", (fetch) => createGoogleGenerativeAI({ apiKey: "made-up", fetch: index.gemini.fetch(key, { fetch }) })("frontier-z"), false], // the id asked for
];

/** @param {check.Seen[]} seen */
const hosts = (seen) => [...new Set(seen.map(({ url }) => url.host))].sort();

describe("The AI SDK", { skip: tooOld }, () => {
  for (const [name, model, named] of MODELS) {
    test(`${name}: a call goes to reflexer and its answer back`, async () => {
      const own = check.mock(answering());
      const result = await generateText({ model: model(own.fetch), prompt: "Hi", maxRetries: 0 });
      assert.equal(result.text, "made up");
      if (named) assert.match(result.response.modelId, /-reflexer$/);
      assert.equal(result.response.headers?.["reflexer-answered-by"], "reflexer");
      assert.deepEqual(hosts(own.seen), [check.REFLEXER]);
    });

    test(`${name}: reflexer busy, the call falls back, and the key reaches only reflexer`, async () => {
      const own = check.mock(answering(true));
      assert.equal((await generateText({ model: model(own.fetch), prompt: "Hi", maxRetries: 0 })).text, "made up");
      assert.equal(hosts(own.seen).length, 2, "it never fell back");
      assert.deepEqual(hosts(own.seen.filter(({ headers }) => [...headers.values()].some((value) => value.includes(key)))), [check.REFLEXER]);
    });

    test(`${name}: the call's timeout ends during reflexer's leg, the call goes to the provider; a stream's does not`, async (t) => {
      t.mock.method(console, "warn", () => {});
      const own = check.mock(answering());
      const stalled = async (/** @type {any} */ input, /** @type {any} */ init) => {
        if (new URL(input).host !== check.REFLEXER) return own.fetch(input, init);
        own.seen.push({ url: new URL(input), headers: new Headers(init.headers), init });
        return check.stalled(init.signal);
      };
      assert.equal((await generateText({ model: model(stalled), prompt: "Hi", maxRetries: 0, timeout: TIMEOUT })).text, "made up");
      assert.equal(hosts(own.seen).length, 2, "it never reached the provider");
      own.seen.length = 0;
      const streamed = streamText({ model: model(stalled), prompt: "Hi", maxRetries: 0, timeout: TIMEOUT, onError: () => {} });
      await assert.rejects(streamed.text);
      await new Promise((done) => setTimeout(done, TIMEOUT)); // a call to the provider would be sent by now
      assert.deepEqual(hosts(own.seen), [check.REFLEXER]);
    });
  }

  test("a stream's chunks reach the client from reflexer", async () => {
    const body = STREAM.map((chunk) => `data: ${JSON.stringify(chunk)}\n\n`).join("") + "data: [DONE]\n\n";
    const own = check.mock(() => new Response(body, { headers: { "content-type": "text/event-stream", "reflexer-status-origin": "reflexer" } }));
    const result = streamText({ model: MODELS[0][1](own.fetch), prompt: "Hi", maxRetries: 0 });
    assert.equal(await result.text, "made up");
    assert.deepEqual(hosts(own.seen), [check.REFLEXER]);
  });
});

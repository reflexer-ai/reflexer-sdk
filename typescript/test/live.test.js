// The live check's own verdicts, on made-up headers: it must fail on a broken wire and pass a sound one.
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import * as check from "../live/check.js";

const headers = (/** @type {Record<string, string>} */ given) => new Headers(given);

describe("Judge", () => {
  test("a sound served answer passes", () => {
    assert.deepEqual(check.judge(headers({ "reflexer-answered-by": "reflexer", "reflexer-cost-nano-usd": "12000", "reflexer-request-id": "x" }),
      "frontier-x-reflexer", 1.2e-05), []);
  });

  test("a served answer without its model or price fails", () => {
    assert.equal(check.judge(headers({ "reflexer-answered-by": "reflexer" }), "frontier-x", undefined).length, 3);
  });

  test("a pass through priced by reflexer fails", () => {
    assert.ok(check.judge(headers({ "reflexer-answered-by": "provider", "reflexer-cost-nano-usd": "5" }), "frontier-x", 0.5).length);
  });

  test("a straight call passes", () => {
    assert.deepEqual(check.judge(headers({}), "frontier-x", undefined), []);
  });

  test("a provider's refusal is judged by the headers it came with, and an error with no response is the check's own", () => {
    const passed = headers({ "reflexer-answered-by": "provider", "reflexer-request-id": "x" });
    const [seen, model] = check.providerRefusal({ status: 401 }, passed);
    assert.equal(seen, passed);
    assert.equal(model, "(the provider's 401)");
    assert.deepEqual(check.judge(seen, model, undefined), []);
    assert.throws(() => check.providerRefusal(new TypeError("fetch failed"), passed), TypeError);
  });
});

describe("Replay", () => {
  test("from its field or reflexer passes", () => {
    assert.ok(!check.replayBroken(headers({}), "from the replay"));
    assert.ok(!check.replayBroken(headers({ "reflexer-answered-by": "reflexer" }), "anything"));
  });

  test("from the provider fails", () => {
    assert.ok(check.replayBroken(headers({ "reflexer-answered-by": "provider" }), "from the replay"));
    assert.ok(check.replayBroken(headers({}), "from the provider"));
  });
});

describe("Endpoint", () => {
  test("no endpoint is taken by default: REFLEXER_BASE must be given", async () => {
    const given = { REFLEXER_BASE: process.env.REFLEXER_BASE, REFLEXER_KEY: process.env.REFLEXER_KEY };
    delete process.env.REFLEXER_BASE;
    process.env.REFLEXER_KEY = "made-up";
    try {
      await assert.rejects(check.main(["openai"]), /set REFLEXER_BASE/);
    } finally {
      for (const [name, value] of Object.entries(given)) (value === undefined ? delete process.env[name] : (process.env[name] = value));
    }
  });
});

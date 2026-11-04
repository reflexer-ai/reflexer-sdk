// What the drift run reads from the source: every provider SDK, or a failure.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, test } from "node:test";
import { lines } from "../tools/tested.js";
import { SDKS } from "../src/index.js";

describe("Tested", () => {
  test("each provider SDK the package names, with its newest major tested and its floor", async () => {
    const { peerDependencies } = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
    assert.equal(lines(SDKS, Object.keys(peerDependencies)).length, Object.keys(peerDependencies).length);
    assert.deepEqual(lines([{ name: "made-up", majors: [7, 8], floor: "7.1.0" }], ["made-up"]), ["made-up 8 7.1.0"]);
  });

  test("a provider SDK missing from the source, or one more, fails", () => {
    assert.throws(() => lines([{ name: "made-up", majors: [7], floor: "7.0.0" }], ["made-up", "other-made-up"]), /names/);
    assert.throws(() => lines([{ name: "made-up", majors: [7], floor: "7.0.0" }, { name: "other-made-up", majors: [1], floor: "1.0.0" }],
      ["made-up"]), /names/);
  });
});

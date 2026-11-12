// The behaviour promises (SECURITY.md), each checked, and each check shown red under a fault planted in a copy of the source.
// Offline, on a mock `fetch`; every value made up.
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import * as check from "./checks.js";

const sdk = await check.load();
const REFLEXER = `${check.REFLEXER} keyed`;
const REPLAYED = { replay_response: { id: "made-up" } };

describe("Promises", () => {
  test("the key reaches only reflexer", async () => {
    assert.deepEqual(await check.hostsGivenTheKey(sdk), [check.REFLEXER]);
  });

  test("through each SDK the key reaches only reflexer", async () => {
    for (const [name, hosts] of Object.entries(await check.throughEachSdk(sdk))) {
      assert.deepEqual(hosts.filter((host) => host.endsWith(" keyed")), [REFLEXER], name);
    }
  });

  test("no option of the client's but its signal and dispatcher reaches reflexer's request", async () => {
    assert.deepEqual(await check.optionsSentToReflexer(sdk), ["dispatcher", "signal"]);
  });

  test("a call reflexer does not take still reaches the provider", async () => {
    assert.ok(await check.aCallReflexerCouldNotTakeReachedTheProvider(sdk));
  });

  test("a replay never reaches the provider", async () => {
    assert.ok(!(await check.aReplayReachedTheProvider(sdk)));
  });

  test("through each SDK a replay never reaches the provider", async () => {
    for (const [name, hosts] of Object.entries(await check.throughEachSdk(sdk, REPLAYED))) {
      assert.deepEqual(hosts, [REFLEXER], name);
    }
  });

  test("reflexer's address must be https", () => {
    assert.ok(!check.aPlainHttpAddressWasTaken(sdk));
  });
});

describe("Broken", () => {
  test("the key on the client's own request turns it red", async () => {
    await check.planted("index.js", "return send(...staysStraight(input, { ...init, signal: afresh(init.signal, began) }));",
      "return send(input, { ...init, headers: { ...init.headers, \"reflexer-key\": way.key } });", async (faulty) => {
        assert.notDeepEqual(await check.hostsGivenTheKey(faulty), [check.REFLEXER]);
        const reached = Object.values(await check.throughEachSdk(faulty)).flat();
        assert.ok(reached.some((host) => host.endsWith(" keyed") && host !== REFLEXER), String(reached));
      });
  });

  test("a redirect followed from reflexer turns it red", async () => {
    await check.planted("index.js", ', redirect: "manual" }', " }", async (faulty) => {
      assert.ok((await check.hostsGivenTheKey(faulty)).includes("elsewhere.example"));
    });
  });

  test("the client's options spread on reflexer's request turn it red", async () => {
    await check.planted("index.js", "{ ...kept, headers: route[1]", "{ ...init, headers: route[1]", async (faulty) => {
      assert.ok((await check.optionsSentToReflexer(faulty)).includes("onMadeUp"));
    });
  });

  test("no fallback turns it red", async () => {
    await check.planted("index.js", "return send(...staysStraight(input, { ...init, signal: afresh(init.signal, began) }));", 'throw new Error("made up");', async (faulty) => {
      assert.ok(!(await check.aCallReflexerCouldNotTakeReachedTheProvider(faulty)));
    });
  });

  test("no replay guard turns it red", async () => {
    await check.planted("logic.js", "export function isReplay(body) {", "export function isReplay(body) {\n  return false;", async (faulty) => {
      assert.ok(await check.aReplayReachedTheProvider(faulty));
      const reached = await check.throughEachSdk(faulty, REPLAYED);
      assert.ok(Object.values(reached).every((hosts) => hosts.some((host) => !host.startsWith(check.REFLEXER))), JSON.stringify(reached));
    });
  });

  test("any address taken turns it red", async () => {
    await check.planted("logic.js", 'if (address.protocol !== "https:" && !', "if (false && !", async (faulty) => {
      assert.ok(check.aPlainHttpAddressWasTaken(faulty));
    });
  });
});

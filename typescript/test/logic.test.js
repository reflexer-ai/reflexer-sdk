// The logic on plain values: no SDK, no server, no network. The vectors are the Python package's (tests/test_logic.py).
import assert from "node:assert/strict";
import { describe, test } from "node:test";
import * as reflexer from "../src/index.js";
import { ANSWER, ASKED, FAILED, GRACE } from "../src/index.js";

const SECRET = "rfx1_aaaaakq_" + "a".repeat(52);
export const KEY = `${SECRET}_${reflexer.checksum(SECRET)}`; // made up, of the form
const WIRE = reflexer.WIRES.openai;
const CHAT = "https://api.openai.com/v1/chat/completions";
const OURS = { "reflexer-request-id": "made-up", "reflexer-status-origin": "reflexer", "content-type": "application/json" };
const LONG = 10 ** 6; // seconds: past every wait

class Clock {
  now = 0;
  read = () => this.now;
}

/** How far apart, in seconds, clients that failed at the same moment try reflexer again. */
function spreadOfReturns(clients = 8) {
  const clock = new Clock();
  const returns = Array.from({ length: clients }, () => {
    const breaker = new reflexer.Breaker(clock.read);
    breaker.note(FAILED, null);
    return breaker.openUntil;
  });
  return Math.max(...returns) - Math.min(...returns);
}

describe("Route", () => {
  const way = () => new reflexer.Reflexer(KEY, WIRE);

  test("a message call goes to reflexer with the key", () => {
    const [url, headers] = way().route(CHAT, { authorization: "Bearer sk-made-up" }) ?? [];
    assert.equal(url, "https://api.reflexer.ai/openai/v1/chat/completions");
    assert.deepEqual(headers, { authorization: "Bearer sk-made-up", "reflexer-key": KEY });
  });

  test("a base of the client's own is named as the upstream", () => {
    const [, headers] = way().route("https://openrouter.ai/api/v1/chat/completions", {}) ?? [];
    assert.equal(headers?.["reflexer-upstream"], "https://openrouter.ai/api");
  });

  test("straight", () => {
    assert.equal(way().route("https://api.openai.com/v1/models", {}), null);
    assert.equal(way().route(CHAT, { [reflexer.PASS_THROUGH]: "1" }), null);
    assert.equal(way().route("http://localhost:11434/v1/chat/completions", {}), null);
    assert.equal(new reflexer.Reflexer(KEY, WIRE, { sample: 0 }).route(CHAT, {}), null);
    for (const host of ["localhost.", "10.0.0.5", "[::1]", "[::ffff:10.0.0.1]"]) {
      assert.equal(way().route(`https://${host}/v1/chat/completions`, {}), null, host);
    }
  });

  test("no userinfo in the upstream", () => {
    const [, headers] = way().route("https://user:made-up@router.example/v1/chat/completions", {}) ?? [];
    assert.equal(headers?.["reflexer-upstream"], "https://router.example");
  });

  test("the query goes with the call, and the client's reflexer headers but the namespace stay behind", () => {
    const [url, headers] = new reflexer.Reflexer(KEY, reflexer.WIRES.gemini)
      .route("https://generativelanguage.googleapis.com/v1beta/models/m:streamGenerateContent?alt=sse",
        { "reflexer-namespace": "made-up", "reflexer-key": "theirs", "reflexer-upstream": "https://elsewhere.example", host: "x" }) ?? [];
    assert.equal(url, "https://api.reflexer.ai/gemini/v1beta/models/m:streamGenerateContent?alt=sse");
    assert.deepEqual(headers, { "reflexer-namespace": "made-up", "reflexer-key": KEY });
  });

  test("a key not of the form throws", () => {
    assert.throws(() => new reflexer.Reflexer(KEY.slice(0, -1) + "a", WIRE));
    assert.throws(() => new reflexer.Reflexer(/** @type {any} */ (undefined), WIRE));
  });

  test("the checksum is the Python package's", () => {
    assert.equal(reflexer.checksum(SECRET), "3vzb2xy");
    assert.equal(reflexer.checksum("made-up"), "3jjuekq");
  });
});

describe("Reachable", () => {
  test("public https only, as Python's ipaddress judges each address", () => {
    const vectors = {
      "10.0.0.5": false, "8.8.8.8": true, "100.64.0.1": false, "127.0.0.1": false, "169.254.1.1": false, "172.16.0.1": false,
      "192.0.0.9": true, "192.0.0.8": false, "192.168.1.1": false, "198.18.0.1": false, "203.0.113.5": false, "224.0.0.1": true,
      "240.0.0.1": false, "255.255.255.255": false, "0.0.0.0": false, "[::1]": false, "[::]": false, "[::ffff:10.0.0.1]": false,
      "[::ffff:8.8.8.8]": true, "[fc00::1]": false, "[fe80::1]": false, "[2001:db8::1]": false, "[2001:4860:4860::8888]": true,
      "[2001:20::1]": true, "[2002::1]": false, "[64:ff9b:1::1]": false, "[64:ff9b::1]": true, "[100::1]": false,
      "[3fff::1]": false, "api.openai.com": true, "localhost.": false,
    };
    for (const [host, expected] of Object.entries(vectors)) {
      assert.equal(reflexer.reachable(new URL(`https://${host}/v1`)), expected, host);
    }
    assert.equal(reflexer.reachable(new URL("http://api.openai.com/v1")), false);
  });

  // The vectors are tests/test_logic.py's: URL's parser reads an IPv4 address as the system's resolver does (inet_aton)
  const OTHER_NOTATIONS = ["10.1", "127.1", "167772161", "0x0a000001", "0300.0250.0.1", "0X0A.1", "0"];

  test("a private address in another notation goes straight", () => {
    const reflexerOf = new reflexer.Reflexer(KEY, WIRE);
    for (const host of OTHER_NOTATIONS) assert.equal(reflexerOf.route(`https://${host}/v1/chat/completions`, {}), null, host);
    for (const host of ["134744072", "0x08080808", "8.526344", "10.1.example"]) {
      assert.notEqual(reflexerOf.route(`https://${host}/v1/chat/completions`, {}), null, host); // public, or a name
    }
  });

  test("Broken: a host read as written, not as URL's parser reads it, would be taken", () => {
    for (const host of OTHER_NOTATIONS.slice(0, -1)) assert.equal(reflexer.reachable({ protocol: "https:", hostname: host }), true, host);
  });
});

describe("Construction", () => {
  test("a trailing slash on the base is no double slash", () => {
    const [url] = new reflexer.Reflexer(KEY, WIRE, { base: "https://reflexer.example/" }).route(CHAT, {}) ?? [];
    assert.equal(url, "https://reflexer.example/openai/v1/chat/completions");
  });

  test("a base that would carry the key in clear throws", () => {
    for (const base of ["http://reflexer.example", null]) {
      assert.throws(() => new reflexer.Reflexer(KEY, WIRE, { base: /** @type {any} */ (base) }), String(base));
    }
    new reflexer.Reflexer(KEY, WIRE, { base: "http://127.0.0.1:8000" }); // a stand-in on this machine
  });

  test("a typo in a wire throws when the client is made", () => {
    assert.throws(() => new reflexer.Reflexer(KEY, /** @type {any} */ ({ provider: "https://made-up.example" })), TypeError);
  });
});

describe("Read", () => {
  /** @param {number} status @param {Record<string, string>} headers */
  const meaning = (status, headers) =>
    reflexer.read(status, headers["reflexer-status-origin"], reflexer.whole(headers["reflexer-straight"]));

  test("each meaning", () => {
    const told = { ...OURS, "reflexer-straight": "5" };
    for (const [status, headers, expected] of /** @type {[number, Record<string, string>, string][]} */ ([
      [200, OURS, ANSWER],
      [200, told, ANSWER], // an answer, not sent again
      [401, OURS, ANSWER], // the client's SDK raises it, naming the reflexer key
      [200, {}, FAILED], // none of our headers: the load balancer's
      [401, {}, FAILED],
      [429, OURS, FAILED],
      [503, OURS, FAILED],
      [529, OURS, FAILED], // anthropic's overload
      [503, told, ASKED],
      [529, told, ASKED],
      [502, { ...OURS, "reflexer-status-origin": "connection" }, ASKED],
      [401, told, GRACE],
      [400, told, GRACE], // gemini's key error
      [500, { ...OURS, "reflexer-status-origin": "provider" }, ANSWER], // a provider's status never trips it
    ])) {
      assert.equal(meaning(status, headers), expected, `${status} ${JSON.stringify(headers)}`);
    }
  });

  test("a straight not of the form is ignored", () => {
    for (const value of ["5.0", "²", "9".repeat(400), "9".repeat(5000), "5\n"]) assert.equal(reflexer.whole(value), null, value);
  });

  test("a 429 saying go straight is no key in its grace", () => {
    assert.equal(meaning(429, { ...OURS, "reflexer-straight": "5" }), ASKED);
  });

  test("a redirect goes straight", () => {
    assert.equal(meaning(307, { ...OURS, "reflexer-status-origin": "provider" }), ASKED);
  });
});

describe("Breaker", () => {
  const made = () => {
    const clock = new Clock();
    return { clock, breaker: new reflexer.Breaker(clock.read) };
  };

  test("a failure opens it for a while", () => {
    const { clock, breaker } = made();
    breaker.note(FAILED, null);
    assert.ok(breaker.isOpen());
    clock.now += reflexer.BACKOFF * (1 + reflexer.JITTER);
    assert.ok(!breaker.isOpen());
  });

  test("failures in a row double up to the cap", () => {
    const { clock, breaker } = made();
    const waits = [];
    for (let n = 0; n < Math.log2(LONG); n++) {
      breaker.note(FAILED, null);
      waits.push(breaker.openUntil - clock.now);
      clock.now = breaker.openUntil;
    }
    assert.ok(waits[0] < 2 * reflexer.BACKOFF);
    assert.ok(waits[1] > waits[0]);
    assert.ok(Math.max(...waits) <= reflexer.BACKOFF_CAP * (1 + reflexer.JITTER));
    assert.ok(waits[waits.length - 1] >= reflexer.BACKOFF_CAP);
  });

  test("an answer ends the row", () => {
    const { clock, breaker } = made();
    breaker.note(FAILED, null);
    clock.now = breaker.openUntil;
    breaker.note(ANSWER, null);
    breaker.note(FAILED, null);
    assert.ok(breaker.openUntil - clock.now < 2 * reflexer.BACKOFF);
  });

  test("calls in flight count as one failure", () => {
    const { breaker } = made();
    for (let n = 0; n < 8; n++) breaker.note(FAILED, null);
    assert.ok(breaker.openUntil <= reflexer.BACKOFF * (1 + reflexer.JITTER));
  });

  test("not counted keeps it closed", () => {
    const { breaker } = made();
    breaker.note(ASKED, null);
    breaker.note(GRACE, null);
    assert.ok(!breaker.isOpen());
  });

  test("told twice in a row opens it for those seconds", () => {
    const { clock, breaker } = made();
    breaker.note(ANSWER, 30);
    assert.ok(!breaker.isOpen());
    breaker.note(ANSWER, 30);
    assert.ok(breaker.isOpen());
    clock.now += 30 * (1 + reflexer.JITTER);
    assert.ok(!breaker.isOpen());
  });

  test("clients failing at once do not return together", () => {
    assert.ok(spreadOfReturns() > 0);
  });

  test("no jitter turns it red", (t) => {
    t.mock.method(Math, "random", () => 0);
    assert.equal(spreadOfReturns(), 0);
  });

  test("the jitter stays small on a long wait", () => {
    const { breaker } = made();
    breaker.note(ANSWER, 86400);
    breaker.note(ANSWER, 86400);
    assert.ok(breaker.openUntil <= 86400 + reflexer.BACKOFF_CAP * reflexer.JITTER);
  });

  test("a shorter wait does not cut a longer one", () => {
    const { breaker } = made();
    breaker.note(ANSWER, 86400);
    breaker.note(ANSWER, 86400);
    breaker.note(ANSWER, 5);
    assert.ok(breaker.openUntil >= 86400);
  });

  test("told twice not in a row does not", () => {
    const { breaker } = made();
    breaker.note(ANSWER, 30);
    breaker.note(ANSWER, null);
    breaker.note(ANSWER, 30);
    assert.ok(!breaker.isOpen());
  });
});

describe("Together", () => {
  const made = () => {
    const clock = new Clock();
    return { clock, way: new reflexer.Reflexer(KEY, WIRE, { clock: clock.read }) };
  };

  test("a failure sends this call and the next straight, and logs only its kind", (t) => {
    const { clock, way } = made();
    const warn = t.mock.method(console, "warn", () => {});
    way.failed(new RangeError("text that could quote a request"));
    assert.equal(warn.mock.callCount(), 1);
    assert.match(warn.mock.calls[0].arguments.join(" "), /RangeError/);
    assert.doesNotMatch(warn.mock.calls[0].arguments.join(" "), /text that could quote/);
    assert.equal(way.route(CHAT, {}), null);
    clock.now += reflexer.BACKOFF * (1 + reflexer.JITTER);
    assert.ok(way.goesStraight(401, new Headers())); // the load balancer's own
    assert.equal(way.route(CHAT, {}), null);
  });

  test("an answer does not", () => {
    const { way } = made();
    assert.ok(!way.goesStraight(200, new Headers(OURS)));
    assert.notEqual(way.route(CHAT, {}), null);
  });

  test("a key in its grace warns", (t) => {
    const { way } = made();
    const warn = t.mock.method(console, "warn", () => {});
    assert.ok(way.goesStraight(401, new Headers({ ...OURS, "reflexer-straight": "3600" })));
    assert.equal(warn.mock.callCount(), 1);
  });
});

describe("Replay", () => {
  const REPLAY = '{"model": "made-up", "replay_response": {"id": "made-up"}}';

  test("an escaped field name is a replay", () => {
    assert.ok(reflexer.isReplay('{"replay\\u005fresponse": {"id": "made-up"}}'));
  });

  test("only the field itself is a replay", () => {
    for (const body of ['{"messages": [{"content": "\\"replay_response\\": 1"}]}', '{"metadata": {"replay_response": 1}}',
      '"replay_response"', 'not json "replay_response"', '["replay_response"]', "", "{}"]) {
      assert.ok(!reflexer.isReplay(body), body);
    }
    assert.ok(reflexer.isReplay(REPLAY));
  });

  test("sampling and an open breaker do not drop a replay", () => {
    const way = new reflexer.Reflexer(KEY, WIRE, { sample: 0 });
    assert.notEqual(way.route(CHAT, {}, true), null);
    way.breaker.openFor(LONG);
    assert.notEqual(way.route(CHAT, {}, true), null);
    assert.equal(way.route(CHAT, { [reflexer.PASS_THROUGH]: "1" }, true), null);
  });
});

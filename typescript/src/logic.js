/**
 * Which calls go to reflexer, and what happens when it fails, on plain values (a URL, headers, a status), with no I/O.
 * `index.js` plugs it into the provider SDK's `fetch`. It changes no answer.
 *
 * Where can my key go? `Reflexer.route`, then `through` in `index.js`. What happens when reflexer fails? `through`.
 */
import { createHash } from "node:crypto";

export const BASE = "https://api.reflexer.ai";
export const SKIP = "reflexer-skip"; // a header the client sets on one call: "true" skips reflexer, "false" does not; it never leaves
export const NOT_A_SKIP = "the Reflexer-Skip header must be true or false: true sends the call directly to the provider, false lets the call go through reflexer";
export const OURS = "reflexer-"; // what starts each header of ours: none leaves for a provider
export const NAMESPACE = "reflexer-namespace"; // a header of ours a client may give reflexer, as the option or on a call
export const ANSWER_HEADER = "reflexer-answer", STORE_HEADER = "reflexer-store", PASS_THROUGH_HEADER = "reflexer-pass-through", TIMEOUT_HEADER = "reflexer-timeout-ms";
export const OPTION_HEADERS = [ANSWER_HEADER, STORE_HEADER, PASS_THROUGH_HEADER, TIMEOUT_HEADER]; // an option's, given by the client or on a call
export const PASSED = [NAMESPACE, ...OPTION_HEADERS]; // the headers of ours a client may give reflexer; none leaves for a provider
/**
 * A client's boolean option: its name in a message, its header, its default (nothing sent), and why it must be true or false.
 * @typedef {[string, string, boolean, string]} Switch
 */
/** @type {Switch} */ const ANSWER_SWITCH = ["answer", ANSWER_HEADER, true, "false asks reflexer not to answer: reflexer replies with an empty response"];
/** @type {Switch} */ const STORE_SWITCH = ["store", STORE_HEADER, true, "false asks reflexer to keep no copy of the call"];
/** @type {Switch} */ const PASS_THROUGH_SWITCH = ["pass-through", PASS_THROUGH_HEADER, false, "true asks reflexer to forward the call to the provider and never answer itself"];
const TIMEOUT_WHY = "the longest reflexer waits for its own answer before it forwards the call to the provider";

/**
 * @typedef {{ reflexerPath: string, provider?: string, calls: RegExp, routers?: (Wire & { host: string })[] }} Wire
 * One wire format: `reflexerPath`, reflexer's path for it; `provider`, the provider's own address, to which no upstream
 * is named; `calls`, the path of the calls that return a model's message, the only ones that go to reflexer; `routers`,
 * optional, each router's wire, by its `host`, for a router with a route of its own at reflexer, taken for the calls it lists.
 */

/** One client's way to reflexer, for one wire format. */
export class Reflexer {
  /**
   * @param {string} key
   * @param {Wire} wire
   * @param {{ base?: string, sample?: number, namespace?: string, answer?: boolean, store?: boolean, passThrough?: boolean, timeoutMs?: number, clock?: () => number }} [options]
   */
  constructor(key, wire, { base = BASE, sample = 1, namespace, answer = true, store = true, passThrough = false, timeoutMs, clock = () => performance.now() / 1000 } = {}) {
    check(key);
    if (namespace != null && !(typeof namespace === "string" && /^[!-~]+(?: [!-~]+)*$/.test(namespace))) {
      throw new Error("a namespace may contain only ASCII letters, digits and signs, and single spaces between them, because the SDK sends it in a header");
    }
    if (typeof wire.reflexerPath !== "string" || !(wire.calls instanceof RegExp)) {
      throw new TypeError("a wire must have a reflexerPath string and a calls RegExp");
    }
    if (typeof sample !== "number" || !(sample >= 0 && sample <= 1)) { // NaN is neither
      throw new Error("sample must be a number from 0 to 1: the share of calls that the SDK sends to reflexer");
    }
    this.key = key;
    this.base = checkedBase(base);
    this.sample = sample;
    this.namespace = namespace;
    this.given = given(namespace, answer, store, passThrough, timeoutMs);
    this.wire = wire;
    this.breaker = new Breaker(clock);
  }

  /**
   * The call as it goes to reflexer, [url, headers]; or null, and it goes straight to the provider.
   * It carries all the client's headers, its provider's key among them, and its query: reflexer passes them on,
   * and stores no key. A replay has nowhere else to go, so neither sampling nor the breaker turns it away.
   * @param {string} url
   * @param {Record<string, string>} headers lowercase names, as `Headers` gives them
   * @returns {[string, Record<string, string>] | null}
   */
  route(url, headers, replay = false) {
    const turnedAway = Math.random() >= this.sample || this.breaker.isOpen(); // a share of calls, no secret
    if (skips(Object.entries(headers).find(([name]) => name === SKIP)?.[1]) || (turnedAway && !replay)) return null;
    const address = new URL(url);
    const router = this.wire.routers?.find((one) => one.host === address.hostname);
    const wire = router?.calls.test(address.pathname) ? router : this.wire;
    const call = wire.calls.exec(address.pathname);
    if (!call || !reachable(address)) return null;
    // `host` holds no user or password of the URL's: none goes to reflexer
    const upstream = `${address.protocol}//${address.host}${address.pathname.slice(0, call.index)}`; // its provider, a router, a runner
    /** @type {Record<string, string>} */
    const ours = { "reflexer-key": this.key };
    if (upstream !== wire.provider) ours["reflexer-upstream"] = upstream;
    const theirs = Object.entries(headers).filter(([name]) =>
      name !== "host" && (PASSED.includes(name) || !name.startsWith(OURS))); // no other header of a client's steers us
    const to = `${this.base}${wire.reflexerPath}${address.pathname.slice(call.index)}${address.search}`;
    return [to, { ...this.given, ...Object.fromEntries(theirs), ...ours }]; // a call's own header wins over the client's option
  }

  /**
   * Whether the call goes straight to the provider, given reflexer's response.
   * @param {number} status
   * @param {Headers} headers
   */
  goesStraight(status, headers) {
    const straightFor = whole(headers.get("reflexer-straight"));
    const meaning = read(status, headers.get("reflexer-status-origin"), straightFor);
    this.breaker.note(meaning, straightFor);
    if (meaning === GRACE) console.warn("reflexer: the reflexer key is revoked; the SDK sends calls directly to the provider until the key's grace period ends");
    return meaning !== ANSWER;
  }

  /**
   * The call to reflexer threw: it goes straight. Only the kind of failure is logged, never its text.
   * @param {unknown} failure
   */
  failed(failure) {
    console.warn("reflexer: the call to reflexer failed (%s); the SDK sends the call directly to the provider", failure instanceof Error ? failure.name : typeof failure);
    this.breaker.note(FAILED, null);
  }
}

/**
 * The headers the client's options give reflexer: each only when it differs from its default, which reflexer takes when
 * nothing is sent. A wrong option throws as the client is made, before anything is sent.
 * @param {string | undefined} namespace @param {unknown} answer @param {unknown} store @param {unknown} passThrough @param {unknown} timeoutMs
 * @returns {Record<string, string>}
 */
function given(namespace, answer, store, passThrough, timeoutMs) {
  /** @type {[string, string][]} */
  const headers = namespace ? [[NAMESPACE, namespace]] : [];
  /** @type {[Switch, unknown][]} */
  const switches = [[ANSWER_SWITCH, answer], [STORE_SWITCH, store], [PASS_THROUGH_SWITCH, passThrough]];
  for (const [[name, header, byDefault, why], value] of switches) {
    if (typeof value !== "boolean") throw new Error(`the ${name} option must be true or false: ${why}`);
    if (value !== byDefault) headers.push([header, String(value)]);
  }
  if (timeoutMs != null) {
    if (!(Number.isInteger(timeoutMs) && /** @type {number} */ (timeoutMs) >= 1)) {
      throw new Error(`the timeout option must be a whole number of milliseconds from 1: ${TIMEOUT_WHY}`);
    }
    headers.push([TIMEOUT_HEADER, String(timeoutMs)]);
  }
  return Object.fromEntries(headers);
}

/**
 * A call's own headers of ours, read before anything is sent: whether its `Reflexer-Skip` skips reflexer (`skips`), and
 * a wrong value of any throws (fail loud). A switch's header is true or false, as the skip's is read; the timeout's, a
 * whole number from 1.
 * @param {{ get(name: string): string | null | undefined }} headers by name in any case, as `Headers` reads them
 */
export function checked(headers) {
  for (const [, header, , why] of [ANSWER_SWITCH, STORE_SWITCH, PASS_THROUGH_SWITCH]) {
    const value = headers.get(header);
    if (value != null && !["true", "false"].includes(trimmed(value).toLowerCase())) {
      throw new Error(`the ${titled(header)} header must be true or false: ${why}`);
    }
  }
  const value = headers.get(TIMEOUT_HEADER);
  if (value != null && !/^[1-9][0-9]*$/.test(trimmed(value))) {
    throw new Error(`the Reflexer-Timeout-Ms header must be a whole number of milliseconds from 1: ${TIMEOUT_WHY}`);
  }
  return skips(headers.get(SKIP));
}

/** @param {string} value */
const trimmed = (value) => String(value).replace(/^[ \t]+|[ \t]+$/g, "");
/** @param {string} header */
const titled = (header) => header.replace(/(^|-)([a-z])/g, (_, dash, letter) => dash + letter.toUpperCase());

/**
 * Whether the client's `Reflexer-Skip` header skips reflexer for this call, by its value in any case and without the
 * whitespace around it, which is not part of a header's value (RFC 9110 5.5): "true" does, "false" does not, and no
 * header does not. Any other value throws, before anything is sent (fail loud).
 * @param {string | null | undefined} value
 */
export function skips(value) {
  const lowered = String(value ?? false).replace(/^[ \t]+|[ \t]+$/g, "").toLowerCase();
  if (lowered !== "true" && lowered !== "false") throw new Error(NOT_A_SKIP);
  return lowered === "true";
}

/**
 * Whether the skip given as a call's option skips reflexer: true does, false or none does not. Anything but a boolean
 * ("false" included) throws `message`, before anything is sent (fail loud).
 * @param {unknown} value @param {string} message
 */
export function skipsByOption(value, message) {
  if (value !== undefined && typeof value !== "boolean") throw new Error(message);
  return value === true;
}

export const REPLAY = "replay_response"; // a body's field: the caller's answer takes the provider's place

/** A replay bypasses the provider: when reflexer cannot take it, it fails, and goes nowhere else. */
export class ReplayNotTaken extends Error {
  name = "ReplayNotTaken";
}

/**
 * Whether a request's body holds the field at its top. Only a body that may name it, plainly or escaped, is parsed.
 * @param {string} body
 */
export function isReplay(body) {
  if (!body.includes(REPLAY) && !body.includes("\\u")) return false;
  try {
    const data = JSON.parse(body);
    return data !== null && typeof data === "object" && !Array.isArray(data) && Object.hasOwn(data, REPLAY);
  } catch {
    return false;
  }
}

// What reflexer's response to a call means
export const ANSWER = "an answer"; // for the client
export const FAILED = "failed"; // straight, and counted by the breaker
export const ASKED = "asked"; // straight, not counted
export const GRACE = "grace"; // straight, not counted, with a warning

/**
 * What a response means: its status, whose doing it is, and whether it says to go straight.
 * @param {number} status
 * @param {string | null | undefined} origin
 * @param {number | null} straightFor
 */
export function read(status, origin, straightFor) {
  const overloaded = status === 429 || status >= 500;
  if (origin == null) return FAILED; // none of our headers: the load balancer's own
  if (origin === "relay" || origin === "connection" || (status >= 300 && status < 400)) return ASKED; // reflexer sent it back to go straight (`connection`: the old name), or a redirect
  if (origin !== "reflexer" || status < 400) return ANSWER; // served, passed through, or the provider's own error
  if (straightFor === null) return overloaded ? FAILED : ANSWER; // reflexer's "not now", or an error the client's SDK raises, naming our key
  return overloaded ? ASKED : GRACE; // reflexer's "not now, for this long", or a key revoked less than a day ago
}

// The breaker, provisional values: a minute or so at most, in exponential backoff with jitter
export const BACKOFF = 1; // seconds after a first failure of reflexer's; doubled at each one in a row
export const BACKOFF_CAP = 60;
export const JITTER = 0.2; // each wait stretched by up to this share of it, at most of the cap, so clients do not come back together
export const OBEYED_AFTER = 2; // responses in a row carrying `Reflexer-Straight`: one server alone sends no one away

/** When every call goes straight, whatever it is: after reflexer's failures, or when told to. */
export class Breaker {
  /** @param {() => number} clock seconds */
  constructor(clock) {
    this.clock = clock;
    this.backoff = BACKOFF;
    this.toldInARow = 0;
    this.openUntil = 0;
  }

  isOpen() {
    return this.clock() < this.openUntil;
  }

  /**
   * @param {string} meaning
   * @param {number | null} straightFor
   */
  note(meaning, straightFor) {
    this.toldInARow = straightFor === null ? 0 : this.toldInARow + 1;
    if (straightFor !== null && this.toldInARow >= OBEYED_AFTER) this.openFor(straightFor);
    if (meaning === ANSWER) this.backoff = BACKOFF;
    if (meaning === FAILED && !this.isOpen()) { // calls already in flight when it failed count once
      this.openFor(this.backoff);
      this.backoff = Math.min(BACKOFF_CAP, this.backoff * 2);
    }
  }

  /** @param {number} seconds */
  openFor(seconds) {
    const wait = seconds + Math.random() * JITTER * Math.min(seconds, BACKOFF_CAP); // a spread of waits, no secret
    this.openUntil = Math.max(this.openUntil, this.clock() + wait);
  }
}

/**
 * A header's whole number, or null for a value reflexer did not send, and so ignored.
 * @param {string | null | undefined} value
 */
export function whole(value) {
  return /^[0-9]{1,18}$/.test(value ?? "") ? Number(value) : null;
}

/**
 * Whether reflexer can pass through to this URL: public https only.
 * @param {URL} address
 */
export function reachable(address) {
  const host = address.hostname.replace(/\.+$/, "");
  if (address.protocol !== "https:" || host === "localhost") return false;
  const ip = literal(host.replace(/^\[(.*)\]$/, "$1"));
  return ip === null || isGlobal(ip); // a name: reflexer resolves and checks it
}

// Not globally reachable, as IANA's special-purpose registries say and as Python's `ipaddress` reads them
const NOT_GLOBAL = ["0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
  "192.0.0.0/24", "192.0.0.170/31", "192.0.2.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
  "240.0.0.0/4", "255.255.255.255/32", "::1/128", "::/128", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32",
  "2002::/16", "3fff::/20", "fc00::/7", "fe80::/10"].map(network);
const GLOBAL_WITHIN = ["192.0.0.9/32", "192.0.0.10/32", "2001:1::1/128", "2001:1::2/128", "2001:3::/32", "2001:4:112::/48",
  "2001:20::/28", "2001:30::/28"].map(network);

/**
 * An IP address as [its value, its width in bits], or null for a name; IPv4-mapped IPv6 as the IPv4 it holds.
 * Of the forms `URL` gives: dotted IPv4, and IPv6 in hex groups.
 * @param {string} host
 * @returns {[bigint, number] | null}
 */
export function literal(host) {
  if (/^(\d+\.){3}\d+$/.test(host)) return [host.split(".").reduce((n, part) => n * 256n + BigInt(part), 0n), 32];
  if (!host.includes(":")) return null;
  const [left, right] = host.split("::").map((half) => (half ? half.split(":") : []));
  const groups = right ? [...left, ...Array(8 - left.length - right.length).fill("0"), ...right] : left;
  const value = groups.reduce((n, group) => n * 65536n + BigInt(`0x${group}`), 0n);
  return value >> 32n === 0xffffn ? [value & 0xffffffffn, 32] : [value, 128];
}

/** @param {string} text */
function network(text) {
  const [address, prefix] = text.split("/");
  return { ip: /** @type {[bigint, number]} */ (literal(address)), prefix: Number(prefix) };
}

/** @param {[bigint, number]} ip */
function isGlobal([value, width]) {
  const within = (/** @type {ReturnType<typeof network>} */ { ip, prefix }) =>
    ip[1] === width && value >> BigInt(width - prefix) === ip[0] >> BigInt(width - prefix);
  return !NOT_GLOBAL.some(within) || GLOBAL_WITHIN.some(within);
}

/**
 * Reflexer's address, which gets the key: https, or plain http on this machine for a stand-in.
 * @param {string} base
 */
export function checkedBase(base) {
  const address = new URL(base);
  if (address.protocol !== "https:" && !["127.0.0.1", "localhost"].includes(address.hostname)) {
    throw new Error(`reflexer's address must use https, to protect the key: ${base}`);
  }
  return String(base).replace(/\/+$/, "");
}

/**
 * A key not of the form throws before anything is sent.
 * @param {unknown} key
 */
export function check(key) {
  const form = /^(rfx1_[a-z2-7]{7}_[a-z2-7]{52})_([a-z2-7]{7})$/.exec(typeof key === "string" ? key : "");
  if (!form || form[2] !== checksum(form[1])) {
    throw new Error("this is not a reflexer key: a reflexer key has the form rfx1_CLIENT_SECRET_CHECK, as given at onboarding");
  }
}

const BASE32 = "abcdefghijklmnopqrstuvwxyz234567";

/**
 * The first four bytes of the text's SHA-256, in lowercase base32 with no padding.
 * @param {string} text
 */
export function checksum(text) {
  const bytes = [...createHash("sha256").update(text).digest().subarray(0, 4)];
  const bits = bytes.map((byte) => byte.toString(2).padStart(8, "0")).join("").padEnd(35, "0");
  return /** @type {string[]} */ (bits.match(/.{5}/g)).map((five) => BASE32.charAt(parseInt(five, 2))).join("");
}

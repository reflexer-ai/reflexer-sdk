/**
 * Reflexer's SDK: a `fetch` for the provider SDK's own `fetch` option. Each call goes where `Reflexer.route` says, by the
 * client's own `fetch`, so its proxy, TLS and connections hold. Whatever fails on the way to reflexer, the client's own call
 * still goes. No answer is touched.
 */
import { BASE, OURS, Reflexer, ReplayNotTaken, isReplay } from "./logic.js";

export * from "./logic.js";

/** @typedef {import("./logic.js").Wire} Wire */
/** @typedef {(input: string | URL | Request, init?: RequestInit) => Promise<Response>} Fetch */
/** @typedef {{ key: string, base?: string, sample?: number, fetch?: Fetch, headersTimeout?: number }} Way */

/** The wire formats: each provider's call paths, and reflexer's path for them. */
export const WIRES = {
  openai: { reflexerPath: "/openai", provider: "https://api.openai.com", calls: /\/v1\/(chat\/completions|responses)$/ },
  azure: { reflexerPath: "/azure", calls: /\/openai\/((deployments\/[^/]+|v1)\/(chat\/completions|responses)|responses)$/ }, // its own host, always named; the last, Azure's dated Responses
  anthropic: { reflexerPath: "/anthropic", provider: "https://api.anthropic.com", calls: /\/v1\/messages$/ },
  gemini: { reflexerPath: "/gemini", provider: "https://generativelanguage.googleapis.com",
    calls: /\/v1(beta)?\/models\/[^/]+:(stream)?[gG]enerateContent$/ },
};

const KEPT = ["method", "signal", "dispatcher"]; // of a client's request options, what reflexer's request keeps
export const HEADERS_TIMEOUT = 300_000; // ms reflexer's leg waits for its answer to start: undici's own default, provisional
const WAYS = new WeakMap(); // each fetch made here, and its way, for an SDK's copy of a client

/**
 * A `fetch` that sends a provider's calls through reflexer: give it as the provider SDK's `fetch` option.
 * `way.fetch`, the client's own, carries both legs; by default the global one, as the provider SDK's default.
 * @param {Wire} wire
 * @param {Way} way
 * @returns {Fetch}
 */
function through(wire, way) {
  const reflexer = new Reflexer(way.key, wire, way);
  /** @type {Fetch} */
  const send = (input, init) => (way.fetch ?? globalThis.fetch)(input, init);

  /** @type {Fetch} */
  async function routed(input, init = {}) {
    tested(new Headers(init.headers));
    try {
      const ours = toReflexer(reflexer, input, init);
      if (ours) {
        const answer = await bounded(send, ours, way.headersTimeout ?? HEADERS_TIMEOUT);
        if (!reflexer.goesStraight(answer.status, answer.headers)) return answer;
        await answer.body?.cancel();
      }
    } catch (failure) {
      reflexer.failed(failure);
    }
    return send(...staysStraight(input, init));
  }

  WAYS.set(routed, way);
  return routed;
}

/**
 * Reflexer's leg, failing when its answer has not started within `ms`: a reflexer that hangs still falls back, whatever
 * the client's own timeout. Once the answer starts, it runs as the client's would.
 * @param {Fetch} send @param {[string, RequestInit]} ours @param {number} ms
 */
async function bounded(send, [url, init], ms) {
  const late = new AbortController();
  const clock = setTimeout(() => late.abort(new DOMException("reflexer's answer did not start in time", "TimeoutError")), ms);
  try {
    return await send(url, { ...init, signal: init.signal ? AbortSignal.any([init.signal, late.signal]) : late.signal });
  } finally {
    clearTimeout(clock);
  }
}

/**
 * Its text, or undefined for a body that could not be sent twice, such as a stream: it goes straight.
 * @param {RequestInit["body"]} body
 */
function textOf(body) {
  if (body == null) return "";
  if (typeof body === "string") return body;
  if (body instanceof ArrayBuffer || ArrayBuffer.isView(body)) return new TextDecoder().decode(body);
  return undefined;
}

/**
 * The call as it goes to reflexer, or null. The client's own request stays as it was.
 * @param {Reflexer} reflexer
 * @param {string | URL | Request} input
 * @param {RequestInit} init
 * @returns {[string, RequestInit] | null}
 */
function toReflexer(reflexer, input, init) {
  const body = textOf(init.body);
  if (input instanceof Request || body === undefined) return null; // a body inside a `Request` is a stream
  const route = reflexer.route(String(input), Object.fromEntries(new Headers(init.headers)), isReplay(body));
  if (!route) return null;
  const kept = Object.fromEntries(Object.entries(init).filter(([name]) => KEPT.includes(name))); // no callback of theirs sees our key
  return [route[0], { ...kept, headers: route[1], body: init.body, redirect: "manual" }]; // a redirect goes straight
}

/**
 * The client's own call, for its provider: no header of ours leaves. A replay never does: the one call that cannot fall back.
 * @param {string | URL | Request} input
 * @param {RequestInit} init
 * @returns {[string | URL | Request, RequestInit]}
 */
function staysStraight(input, init) {
  const body = textOf(init.body);
  if (body !== undefined && isReplay(body)) throw new ReplayNotTaken("reflexer did not take this replay, and a replay does not go to the provider");
  const headers = new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined));
  for (const name of [...headers.keys()].filter((name) => name.startsWith(OURS))) headers.delete(name);
  return [input, { ...init, headers }];
}

/**
 * One provider's `fetch` maker: `openai.fetch(reflexerKey)`, with `{ base, sample, fetch }` as options.
 * `stock`, the `fetch` its SDK uses when given none, if not the global one.
 * @param {Wire} wire
 * @param {Fetch} [stock]
 */
function provider(wire, stock) {
  return {
    /** @param {string} key @param {Omit<Way, "key">} [options] */
    fetch: (key, options = {}) => through(wire, { ...options, key, fetch: options.fetch ?? stock }),
  };
}

/**
 * As google-genai's own, on Node and given no fetch: Node's global dispatcher, kept where undici documents it, without
 * undici's 300 s timeouts. Reflexer's leg keeps a bound of its own (`bounded`).
 */
const untimed = {
  /** @param {object} options @param {object} handler */
  dispatch(options, handler) {
    new Headers(); // Node makes its global dispatcher on first use
    return /** @type {any} */ (globalThis)[Symbol.for("undici.globalDispatcher.1")].dispatch({ ...options, headersTimeout: 0, bodyTimeout: 0 }, handler);
  },
};

export const openai = provider(WIRES.openai);
export const azure = provider(WIRES.azure);
export const anthropic = provider(WIRES.anthropic);
export const gemini = provider(WIRES.gemini, (input, init) => globalThis.fetch(input, { dispatcher: /** @type {any} */ (untimed), ...init }));

/**
 * Each provider SDK's majors this is tested on, its oldest release tested, and how its calls name its version, in their
 * user agent. google-genai takes a `fetch` from 2.23.0, and adds its untimed dispatcher, which reflexer's line keeps, from 2.29.0.
 */
export const SDKS = [
  { name: "openai", majors: [7], floor: "7.0.0", label: /OpenAI\/JS ([0-9.]+)/ },
  { name: "@anthropic-ai/sdk", majors: [1], floor: "1.0.0", label: /Anthropic\/JS ([0-9.]+)/ },
  { name: "@google/genai", majors: [2], floor: "2.29.0", label: /\bgoogle-genai-sdk\/([0-9.]+)/ },
];

/**
 * A provider SDK runs only on the majors it was tested on, from its floor: a new major, or an older release, throws, never misroutes.
 * @param {string} name @param {string} version
 */
export function supported(name, version) {
  const { majors, floor } = /** @type {typeof SDKS[0]} */ (SDKS.find((sdk) => sdk.name === name));
  const sortable = (/** @type {string} */ text) => text.split(".").map((part) => part.padStart(9, "0")).join("."); // in text order as in version order
  const fails = !majors.includes(Number(version.split(".")[0])) || sortable(version) < sortable(floor);
  if (fails) throw new Error(`reflexer is tested on ${name} ${majors} from ${floor}, not ${version}`);
}

/**
 * The provider SDKs a call's user agent names, each checked by `supported`. A call naming none goes as before: the fetch
 * form takes a provider's calls from any client.
 * @param {Headers} headers
 */
export function tested(headers) {
  const label = `${headers.get("user-agent") ?? ""} ${headers.get("x-goog-api-client") ?? ""}`;
  const named = SDKS.map(({ name, label: pattern }) => [name, pattern.exec(label)?.[1]]).filter(([, version]) => version);
  for (const [name, version] of named) supported(String(name), String(version));
  return named.map(([name]) => name);
}

/**
 * @template {abstract new (...args: any) => any} C
 * @typedef {(new (options?: ConstructorParameters<C>[0] & { reflexerKey?: string, reflexerBase?: string, sample?: number }) => InstanceType<C>) & C} Reflexed
 */

/**
 * The one line: `new Stock(config)` becomes `new Client({ ...config, reflexerKey })`, for an SDK client class whose
 * options take `fetch` and whose copies are made by `withOptions`. The SDK's own copies hand our `fetch` back in, with no
 * key; a copy given a `fetch` of the client's goes through reflexer the same way.
 * @template {new (options?: any) => { withOptions(options: any): any }} C
 * @param {C} Stock
 * @param {Wire} wire
 * @returns {Reflexed<C>}
 */
export function client(Stock, wire) {
  // @ts-ignore: a mixin's constructor takes the stock options, and ours
  class Client extends Stock {
    #way;

    /** @param {any} options */
    constructor({ reflexerKey, reflexerBase = BASE, sample = 1, ...config } = {}) {
      const routed = WAYS.has(config.fetch) ? config.fetch : through(wire, { key: reflexerKey, base: reflexerBase, sample, fetch: config.fetch });
      super({ ...config, fetch: routed });
      this.#way = WAYS.get(routed);
    }

    /** @param {any} options */
    withOptions(options) {
      const own = options?.fetch;
      return super.withOptions(own === undefined || WAYS.has(own) ? options : { ...options, fetch: through(wire, { ...this.#way, fetch: own }) });
    }
  }

  Object.defineProperty(Client, "name", { value: Stock.name }); // the SDK names its client by it, in its user agent
  return /** @type {any} */ (Client);
}

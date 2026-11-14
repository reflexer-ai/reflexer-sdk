/**
 * The AI SDK's Bedrock provider (`@ai-sdk/amazon-bedrock`), through reflexer, apart from the files every provider
 * shares: `fetch`, the provider's `fetch` option, and `middleware`, for `wrapLanguageModel`. A call carrying a Bedrock
 * API key goes as `./bedrock.js`'s `fetch` sends it; so does a signed one (SigV4), but its fallback: the provider signs
 * inside its own fetch, before ours, and no hook of its signs anew, so the fallback is the same signed call. Reflexer's
 * leg is bounded, to its answer's head, by what is left of the signature's window, by the clock the provider signs by
 * (this machine's, uncorrected), so the fallback reaches Bedrock while its signature holds.
 */
import { fetch as bedrockFetch, skipped } from "./bedrock.js";
import { BASE, OURS, SKIP, bounded, skips, skipsByOption } from "./logic.js";

const NOT_A_SKIP_OPTION = "the providerOptions.reflexer.skip option must be true or false: true sends the call directly to the provider, false lets the call go through reflexer";

export const WINDOW = { header: "x-amz-date", ms: 300_000, margin: 30_000 }; // a signature's: AWS's five minutes; the margin provisional

/**
 * Milliseconds reflexer's leg may take so that Bedrock still takes the call's signature after it, or null for a call
 * with no signing time (a Bedrock API key's).
 * @param {Headers} headers
 */
export function left(headers) {
  const at = Date.parse((headers.get(WINDOW.header) ?? "").replace(/^(\d{4})(\d\d)(\d\d)T(\d\d)(\d\d)(\d\d)Z$/, "$1-$2-$3T$4:$5:$6Z"));
  return Number.isNaN(at) ? null : at + WINDOW.ms - WINDOW.margin - Date.now();
}

/**
 * The AI SDK's `fetch` line: `./bedrock.js`'s, a signed call's leg to reflexer bounded by its window. A signed call with
 * no time left goes straight, as does one holding a header of ours, which the provider signs with the call's own and its
 * fallback would drop (`Reflexer-Namespace`).
 * @param {string} key @param {any} [options] `{ base, sample, namespace, answer, store, passThrough, timeoutMs, fetch, headersTimeout }`
 */
export function fetch(key, options = {}) {
  const own = (/** @type {any} */ input, /** @type {any} */ init) => (options.fetch ?? globalThis.fetch)(input, init);
  const base = new URL(options.base ?? BASE).origin;
  const windowed = async (/** @type {any} */ input, /** @type {any} */ init = {}) => {
    const time = String(input).startsWith(base) ? left(new Headers(init.headers)) : null;
    if (time === null) return own(input, init);
    return bounded((signal) => own(input, { ...init, signal }), init.signal, time, "reflexer's answer did not start while the signature holds");
  };
  const through = bedrockFetch(key, { ...options, fetch: windowed, signed: true });
  return (/** @type {any} */ input, /** @type {any} */ init = {}) => {
    const headers = new Headers(init.headers), time = left(headers);
    const asSigned = time !== null && (time <= 0 || [...headers.keys()].some((name) => name.startsWith(OURS)));
    return asSigned ? skipped(() => through(input, init)) : through(input, init);
  };
}

/**
 * The AI SDK's language model middleware (`wrapLanguageModel`): the skip, as the call's header or as its argument
 * (`providerOptions: { reflexer: { skip: true } }`), taken off before the provider signs; the call then goes straight. The
 * header's value "false" skips nothing; any other value but "true" throws, before anything is sent, as does an argument
 * that is not a boolean.
 */
export const middleware = {
  /** @param {any} options */
  transformParams: async ({ params }) => {
    const headers = Object.entries(params.headers ?? {});
    const given = headers.filter(([name]) => name.toLowerCase() === SKIP).map(([, value]) => skips(value)); // a wrong value throws
    const { reflexer, ...theirs } = params.providerOptions ?? {};
    const option = skipsByOption(reflexer?.skip, NOT_A_SKIP_OPTION); // a wrong value throws
    if (!given.length && !option) return params;
    const left = { ...params, headers: Object.fromEntries(headers.filter(([name]) => name.toLowerCase() !== SKIP)) };
    return given.includes(true) || option ? { ...left, providerOptions: theirs, reflexerSkipped: true } : left;
  },
  /** @param {any} options */
  wrapGenerate: async ({ doGenerate, params }) => (params.reflexerSkipped ? skipped(doGenerate) : doGenerate()),
  /** @param {any} options */
  wrapStream: async ({ doStream, params }) => (params.reflexerSkipped ? skipped(doStream) : doStream()),
};

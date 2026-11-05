// What the promise tests check, on the package as loaded from a folder: the source, or a copy with one fault planted.
// Offline: every call ends at a mock `fetch`, which follows redirects as `fetch` does. Every value made up.
import assert from "node:assert/strict";
import { cp, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const PACKAGE = fileURLToPath(new URL("..", import.meta.url));

// Offline: a call to anywhere but this machine fails, so a provider SDK that ignores the `fetch` it is given reaches no one
const realFetch = globalThis.fetch;
globalThis.fetch = (input, init) => new URL(input instanceof Request ? input.url : input).hostname === "127.0.0.1"
  ? realFetch(input, init) : Promise.reject(new TypeError("offline: the tests call no one but this machine"));
export const REFLEXER = "api.reflexer.ai";
export const CHAT = "https://api.openai.com/v1/chat/completions";
export const REPLAY = '{"model": "made-up", "replay_response": {"id": "made-up"}}';
const FAULTS = ".fault-"; // what starts each folder a fault is planted in, inside the package's own

/** The package's modules, from `src` in `root`. */
export async function load(root = PACKAGE) {
  const at = (/** @type {string} */ name) => import(pathToFileURL(join(root, "src", name)).href);
  const index = await at("index.js");
  const provider = (/** @type {string} */ name) => at(name).catch((failure) => ({ failure })); // as a client would see it fail
  const secret = "rfx1_aaaaakq_" + "a".repeat(52);
  return { index, openai: await provider("openai.js"), anthropic: await provider("anthropic.js"), gemini: await provider("gemini.js"),
    bedrock: await at("bedrock.js"), key: `${secret}_${index.checksum(secret)}` };
}

/**
 * The package with one fault planted: `from`, found once in `file`, becomes `to`. Its folder is removed after `use`.
 * @param {string} file @param {string} from @param {string} to @param {(sdk: Awaited<ReturnType<typeof load>>) => Promise<void>} use
 */
export async function planted(file, from, to, use) {
  const root = await mkdtemp(join(PACKAGE, FAULTS));
  try {
    await cp(join(PACKAGE, "src"), join(root, "src"), { recursive: true });
    const text = await readFile(join(root, "src", file), "utf8");
    assert.equal(text.split(from).length, 2, `the fault's text, once in ${file}: ${from}`);
    await writeFile(join(root, "src", file), text.replace(from, () => to));
    await use(await load(root));
  } finally {
    assert.ok(root.startsWith(join(PACKAGE, FAULTS)), root); // only the folder made above
    await rm(root, { recursive: true });
  }
}

/** @typedef {{ url: URL, headers: Headers, init: RequestInit }} Seen */
/** @typedef {(url: URL, headers: Headers) => Response} Answer */

/** A client's own `fetch`, answering by `answer`; every request it received, in `seen`. @param {Answer} answer */
export function mock(answer) {
  /** @type {Seen[]} */
  const seen = [];
  /** @param {string | URL | Request} input @param {RequestInit} [init] @returns {Promise<Response>} */
  const fetch = async (input, init = {}) => {
    const url = new URL(input instanceof Request ? input.url : input);
    const headers = new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined));
    init.signal?.throwIfAborted();
    seen.push({ url, headers, init });
    const response = answer(url, headers);
    const location = response.headers.get("location");
    if (location && init.redirect !== "manual") return fetch(location, init); // as `fetch` follows one
    return response;
  };
  return { fetch, seen };
}

/** @param {string} what */
const json = (what, status = 200, headers = {}) =>
  new Response(JSON.stringify(what), { status, headers: { "content-type": "application/json", ...headers } });

/** Each provider's own answer, of its form. @param {URL} url */
export function providers(url) {
  if (url.host === "api.anthropic.com") {
    return json({ id: "made-up", type: "message", role: "assistant", content: [], model: "made-up", stop_reason: "end_turn",
      usage: { input_tokens: 1, output_tokens: 1 } });
  }
  if (url.host.endsWith("googleapis.com")) return json({ candidates: [], responseId: "made-up" });
  return json({ id: "made-up", object: "chat.completion", created: 0, model: "made-up", choices: [], from: "provider" });
}

/** @type {Answer} */
export const busy = (url) =>
  url.host === REFLEXER ? new Response(null, { status: 503, headers: { "reflexer-status-origin": "reflexer" } }) : providers(url);

/** @type {Answer} */
export const down = (url) => {
  if (url.host === REFLEXER) throw new TypeError("fetch failed");
  return providers(url);
};

/** @type {Answer} */
export const redirected = (url) => url.host === REFLEXER
  ? new Response(null, { status: 307, headers: { location: "https://elsewhere.example/v1", "reflexer-status-origin": "reflexer" } })
  : providers(url);

/** @type {Answer} */
export const served = (url) => json({ id: "made-up", from: url.host === REFLEXER ? "reflexer" : "provider" }, 200,
  { "reflexer-status-origin": "reflexer", "reflexer-answered-by": "reflexer" });

/** A call, as a provider SDK makes it, through `sdk`'s fetch over a client's own. @param {any} sdk @param {Answer} answer */
export async function post(sdk, answer, body = "{}", init = {}) {
  const own = mock(answer);
  const result = await sdk.index.openai.fetch(sdk.key, { fetch: own.fetch })(CHAT, { method: "POST", body, ...init })
    .then((/** @type {Response} */ response) => response.json(), (/** @type {Error} */ failure) => failure);
  return { result, seen: own.seen };
}

/** Every host that received the reflexer key, over a fallback, a failure and a redirect. @param {any} sdk */
export async function hostsGivenTheKey(sdk) {
  const given = new Set();
  for (const answer of [busy, down, redirected]) {
    const { seen } = await post(sdk, answer, "{}", { headers: { authorization: "Bearer sk-made-up" } });
    for (const { url, headers } of seen) if (headers.has("reflexer-key")) given.add(url.host);
  }
  return [...given];
}

/** @param {any} sdk */
export async function aReplayReachedTheProvider(sdk) {
  for (const answer of [busy, down]) {
    const { seen } = await post(sdk, answer, REPLAY);
    if (seen.some(({ url }) => url.host !== REFLEXER)) return true;
  }
  return false;
}

/** @param {any} sdk */
export async function aCallReflexerCouldNotTakeReachedTheProvider(sdk) {
  for (const answer of [busy, down]) {
    const { result } = await post(sdk, answer);
    if (result?.from !== "provider") return false;
  }
  return true;
}

/** @param {any} sdk */
export function aPlainHttpAddressWasTaken(sdk) {
  try {
    sdk.index.openai.fetch(sdk.key, { base: "http://api.reflexer.example" });
    return true;
  } catch {
    return false;
  }
}

/** The names of the client's request options that reach reflexer's request. @param {any} sdk */
export async function optionsSentToReflexer(sdk) {
  const options = { signal: new AbortController().signal, dispatcher: {}, onMadeUp: () => {}, cache: "no-store", credentials: "include" };
  const { seen } = await post(sdk, busy, "{}", options);
  return Object.keys(seen.find(({ url }) => url.host === REFLEXER)?.init ?? {}).filter((name) => name in options).sort();
}

/** The stock classes, as a client imports them. */
export const stock = {
  OpenAI: (await import("openai")).OpenAI,
  Anthropic: (await import("@anthropic-ai/sdk")).Anthropic,
  GoogleGenAI: (await import("@google/genai")).GoogleGenAI,
  ChatOpenAI: (await import("@langchain/openai")).ChatOpenAI,
  ChatAnthropic: (await import("@langchain/anthropic")).ChatAnthropic,
  AzureChatOpenAI: (await import("@langchain/openai")).AzureChatOpenAI,
};

/**
 * Each provider SDK's client, in both forms and as its own copy, through `sdk` over a client's own `fetch`:
 * [name, a message call made with that fetch and `extra` in its body].
 * @param {any} sdk @returns {[string, (fetch: any, extra: object) => Promise<unknown>][]}
 */
export function sdkCalls(sdk) {
  const { key, index } = sdk;
  const options = { apiKey: "made-up", maxRetries: 0 };
  const azure = { endpoint: "https://made-up.openai.azure.com", apiVersion: "2024-10-21", deployment: "made-up" };
  const chat = (/** @type {any} */ client, /** @type {object} */ extra) => client.chat.completions.create({ model: "m", messages: [], ...extra });
  const messages = (/** @type {any} */ client, /** @type {object} */ extra) =>
    client.messages.create({ model: "m", max_tokens: 1, messages: [], ...extra });
  const generate = (/** @type {any} */ client, /** @type {object} */ extra) =>
    client.models.generateContent({ model: "m", contents: "x", config: { httpOptions: { extraBody: extra } } });
  return [
    ["openai, by fetch", (fetch, extra) => chat(new stock.OpenAI({ ...options, fetch: index.openai.fetch(key, { fetch }) }), extra)],
    ["openai", (fetch, extra) => chat(new sdk.openai.OpenAI({ ...options, reflexerKey: key, fetch }), extra)],
    ["openai, a copy", (fetch, extra) => chat(new sdk.openai.OpenAI({ ...options, reflexerKey: key, fetch }).withOptions({ timeout: 1000 }), extra)],
    ["azure", (fetch, extra) => chat(new sdk.openai.AzureOpenAI({ ...options, ...azure, reflexerKey: key, fetch }), extra)],
    ["anthropic, by fetch", (fetch, extra) => messages(new stock.Anthropic({ ...options, fetch: index.anthropic.fetch(key, { fetch }) }), extra)],
    ["anthropic", (fetch, extra) => messages(new sdk.anthropic.Anthropic({ ...options, reflexerKey: key, fetch }), extra)],
    ["anthropic, a copy", (fetch, extra) =>
      messages(new sdk.anthropic.Anthropic({ ...options, reflexerKey: key, fetch }).withOptions({ timeout: 1000 }), extra)],
    ["gemini, by fetch", (fetch, extra) =>
      generate(new stock.GoogleGenAI({ apiKey: "made-up", httpOptions: { fetch: index.gemini.fetch(key, { fetch }) } }), extra)],
    ["gemini", (fetch, extra) => generate(new sdk.gemini.GoogleGenAI({ apiKey: "made-up", reflexerKey: key, httpOptions: { fetch } }), extra)],
    ["langchain openai, by fetch", (fetch, extra) => new stock.ChatOpenAI({ model: "m", apiKey: "made-up", maxRetries: 0, modelKwargs: extra,
      configuration: { fetch: index.openai.fetch(key, { fetch }) } }).invoke("x")],
    ["langchain azure, by fetch", (fetch, extra) => new stock.AzureChatOpenAI({ azureOpenAIApiKey: "made-up", azureOpenAIApiInstanceName: "made-up",
      azureOpenAIApiDeploymentName: "made-up", azureOpenAIApiVersion: azure.apiVersion, maxRetries: 0, modelKwargs: extra,
      configuration: { fetch: index.azure.fetch(key, { fetch }) } }).invoke("x")],
  ];
}

/** {sdk: each "host keyed" or "host unkeyed" its call reached}, `answer` answering every host. @param {any} sdk */
export async function throughEachSdk(sdk, extra = {}, answer = busy) {
  /** @type {Record<string, string[]>} */
  const found = {};
  for (const [name, call] of sdkCalls(sdk)) {
    const own = mock(answer);
    try {
      await call(own.fetch, extra);
    } catch {
      // the made-up answers are no real ones; where the call went is what is checked
    }
    found[name] = [...new Set(own.seen.map(({ url, headers }) => `${url.host} ${headers.has("reflexer-key") ? "keyed" : "unkeyed"}`))].sort();
  }
  return found;
}

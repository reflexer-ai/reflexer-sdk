// One run against a real reflexer endpoint, through each provider SDK: what the stand-ins cannot show.
//
//   REFLEXER_BASE=https://... REFLEXER_KEY=rfx1_... OPENAI_API_KEY=... node live/check.js [openai anthropic gemini replay]
//
// Each SDK named, with its provider key in the environment (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) and
// optionally its model (`OPENAI_MODEL`, ...) and base URL (`OPENAI_BASE_URL`, ...: a provider stand-in), makes one call.
// It prints who answered, the model, the price and the request id, and fails on what breaks the SDK's wire: a served answer
// with no `-reflexer` model or no price, or a replay answered by anyone but reflexer or its field. A provider's refusal of a
// made-up key, passed through, is judged as an answer. Never run by CI: it needs the endpoint and keys.
import { pathToFileURL } from "node:url";

const MODELS = { openai: "gpt-4o-mini", anthropic: "claude-haiku-4-5", gemini: "gemini-2.5-flash" }; // defaults, any may be given

/** @param {string} name @param {string} [fallback] */
function env(name, fallback) {
  const value = process.env[name] ?? fallback;
  if (value === undefined) throw new Error(`set ${name}`);
  return value;
}

export const REPLAY = { id: "made-up", object: "chat.completion", created: 1, model: "made-up",
  choices: [{ index: 0, finish_reason: "stop", message: { role: "assistant", content: "from the replay" } }],
  usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } };

/** The client's own `fetch`, keeping the last response it got, whose headers are judged. */
function recorded() {
  const seen = { last: /** @type {Response | undefined} */ (undefined) };
  /** @param {any} input @param {any} init */
  const fetch = async (input, init) => (seen.last = await globalThis.fetch(input, init));
  return { fetch, headers: () => seen.last?.headers ?? new Headers() };
}

/** One call through `sdk`'s one-line class: [the headers it got, the model it names, its usage's cost]. */
async function call(/** @type {string} */ sdk, /** @type {string} */ key, /** @type {string} */ base) {
  const model = env(`${sdk.toUpperCase()}_MODEL`, /** @type {any} */ (MODELS)[sdk]);
  const apiKey = env(`${sdk.toUpperCase()}_API_KEY`), baseURL = process.env[`${sdk.toUpperCase()}_BASE_URL`];
  const own = recorded(), on = { reflexerKey: key, reflexerBase: base, fetch: own.fetch, maxRetries: 0 };
  try {
    if (sdk === "openai") {
      const { OpenAI } = await import("@reflexer-ai/sdk/openai");
      const made = await new OpenAI({ apiKey, baseURL, ...on }).chat.completions.create({ model, messages: [{ role: "user", content: "Say hi" }] });
      return [own.headers(), made.model, /** @type {any} */ (made.usage)?.cost];
    }
    if (sdk === "anthropic") {
      const { Anthropic } = await import("@reflexer-ai/sdk/anthropic");
      const made = await new Anthropic({ apiKey, baseURL, ...on }).messages.create({ model, max_tokens: 16, messages: [{ role: "user", content: "Say hi" }] });
      return [own.headers(), made.model, /** @type {any} */ (made.usage)?.cost];
    }
    const { GoogleGenAI } = await import("@reflexer-ai/sdk/gemini");
    const httpOptions = { fetch: own.fetch, ...(baseURL && { baseUrl: baseURL }) };
    const made = await new GoogleGenAI({ apiKey, reflexerKey: key, reflexerBase: base, httpOptions }).models.generateContent({ model, contents: "Say hi" });
    return [own.headers(), made.modelVersion, undefined]; // gemini's object holds no price: its headers do
  } catch (error) {
    return providerRefusal(error, own.headers());
  }
}

/**
 * A provider's own error, passed through untouched: the headers it came with, read as an answer's would be. An error
 * with no response behind it is the check's own failure.
 * @param {any} error @param {Headers} headers
 */
export function providerRefusal(error, headers) {
  const status = error?.status ?? error?.code;
  if (typeof status !== "number") throw error;
  return [headers, `(the provider's ${status})`, undefined];
}

/**
 * What breaks the wire, as text; empty when it holds.
 * @param {Headers} headers @param {unknown} model @param {unknown} cost
 */
export function judge(headers, model, cost) {
  const answered = headers.get("reflexer-answered-by");
  if (answered === "reflexer") {
    return /** @type {[string, boolean][]} */ ([
      [`a served answer's model is ${model}, not ending in -reflexer`, !String(model).endsWith("-reflexer")],
      ["a served answer with no Reflexer-Cost", headers.get("reflexer-cost") === null],
      ["a served answer with no request id", headers.get("reflexer-request-id") === null],
    ]).filter(([, broken]) => broken).map(([problem]) => problem);
  }
  if (answered === "provider") {
    return cost != null && ![null, "0"].includes(headers.get("reflexer-cost")) ? ["a pass through with a price written by reflexer"] : [];
  }
  return []; // no header of reflexer's: the call went straight, which the SDK allows
}

/**
 * A replay is answered by reflexer, or from its field: never by anyone else.
 * @param {Headers} headers @param {string} text
 */
export function replayBroken(headers, text) {
  const by = headers.get("reflexer-answered-by");
  return (by !== null && by !== "reflexer") || (by === null && text !== "from the replay");
}

/** A request carrying `replay_response` (OpenAI's format), plain or streamed: [its headers, its text]. */
async function replayed(/** @type {string} */ key, /** @type {string} */ base, streamed = false) {
  const { OpenAI } = await import("@reflexer-ai/sdk/openai");
  const own = recorded();
  const client = new OpenAI({ apiKey: env("OPENAI_API_KEY"), reflexerKey: key, reflexerBase: base, fetch: own.fetch, maxRetries: 0 });
  const asked = { model: env("OPENAI_MODEL", MODELS.openai), messages: [{ role: /** @type {const} */ ("user"), content: "Say hi" }] };
  if (!streamed) {
    const made = await client.chat.completions.create({ ...asked, replay_response: REPLAY });
    return [own.headers(), made.choices[0]?.message.content ?? ""];
  }
  const chunk = { ...REPLAY, object: "chat.completion.chunk", choices: [{ index: 0, finish_reason: null,
    delta: { role: "assistant", content: "from the replay" } }] };
  const stream = await client.chat.completions.create({ ...asked, stream: true, replay_response: `data: ${JSON.stringify(chunk)}\n\ndata: [DONE]\n\n` });
  let text = "";
  for await (const event of stream) text += event.choices[0]?.delta.content ?? "";
  return [own.headers(), text];
}

/** @param {string[]} sdks */
export async function main(sdks) {
  const key = env("REFLEXER_KEY"), base = env("REFLEXER_BASE"); // no default: a key goes to the endpoint named
  let failed = false;
  if (sdks.includes("replay")) {
    for (const [way, streamed] of /** @type {[string, boolean][]} */ ([["replay", false], ["replay, streamed", true]])) {
      const [headers, text] = await replayed(key, base, streamed);
      console.log(`${way}: answered by ${headers.get("reflexer-answered-by") ?? "its field"}, text ${JSON.stringify(text)}, `
        + `Reflexer-Cost ${headers.get("reflexer-cost")}, id ${headers.get("reflexer-request-id")}`);
      if (replayBroken(headers, text)) {
        console.error("  broken: a replay answered by someone else than reflexer or its field");
        failed = true;
      }
    }
  }
  for (const sdk of sdks.filter((sdk) => sdk !== "replay")) {
    const [headers, model, cost] = /** @type {[Headers, unknown, unknown]} */ (await call(sdk, key, base));
    console.log(`${sdk}: answered by ${headers.get("reflexer-answered-by") ?? "the provider, straight"}, model ${model}, `
      + `Reflexer-Cost ${headers.get("reflexer-cost")}, usage.cost ${cost}, id ${headers.get("reflexer-request-id")}`);
    for (const problem of judge(headers, model, cost)) {
      console.error(`  broken: ${problem}`);
      failed = true;
    }
  }
  return failed ? 1 : 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exitCode = await main(process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(MODELS));
}

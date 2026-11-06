// The documentation's `js` examples, each run as written, offline: every `fetch` and AWS JS's Node handlers answer as
// reflexer and the providers would, with made-up keys in the environment. Each block's comment says what it must show,
// as `tests/acceptance/test_docs.py` reads it: served or straight, and `bedrock` to run it with a Bedrock API key and
// signed. A share of calls (`sample`) is drawn at the middle of its range, as there.
import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import net from "node:net";
import { join } from "node:path";
import { Readable } from "node:stream";
import { describe, test } from "node:test";
import { pathToFileURL } from "node:url";
import { format } from "node:util";
import { NodeHttp2Handler, NodeHttpHandler } from "@smithy/node-http-handler";
import * as check from "./checks.js";

const { key } = await check.load();
const ROOT = join(check.PACKAGE, "..");
const DOCS = [join(ROOT, "README.md"), ...(await readdir(join(ROOT, "docs"), { recursive: true })).filter((name) => name.endsWith(".md")).map((name) => join(ROOT, "docs", name))];
const BLOCK = /(?:<!-- example: ([a-z ]+) -->\n)?```js\n([\s\S]*?)^```/gm;
const TEXT = { served: "served by reflexer", straight: "from the provider" };
const WAYS = { key: "Bearer", signed: "AWS4-HMAC-SHA256" }; // Bedrock's, by the scheme its calls carry
const ENVIRONMENT = {
  REFLEXER_KEY: key, OPENAI_API_KEY: "sk-made-up", ANTHROPIC_API_KEY: "sk-ant-made-up", GOOGLE_API_KEY: "ai-made-up",
  GOOGLE_GENERATIVE_AI_API_KEY: "ai-made-up", AZURE_OPENAI_API_KEY: "az-made-up", AZURE_OPENAI_ENDPOINT: "https://made-up.openai.azure.com",
  AZURE_OPENAI_API_INSTANCE_NAME: "made-up", AZURE_OPENAI_API_VERSION: "2024-10-21", OPENAI_API_VERSION: "2024-10-21",
  AWS_ACCESS_KEY_ID: "AKIDMADEUPMADEUP0001", AWS_SECRET_ACCESS_KEY: "made-up-secret", AWS_REGION: "us-east-1",
  AWS_CONFIG_FILE: "/nonexistent/aws-config", AWS_SHARED_CREDENTIALS_FILE: "/nonexistent/aws-credentials", AWS_EC2_METADATA_DISABLED: "true",
};
const BEARER = "ABSKbWFkZS11cC1iZWRyb2NrLWtleQ=="; // a Bedrock API key's form, made up
const LIMIT = 30_000; // ms a block may take: one that hangs fails

/** A provider's answer to a call, in its format, by its path: [content type, body]. @param {string} path @param {string} text */
function answer(path, text, served = false) {
  const model = served ? "your-model-reflexer" : "your-model";
  const usage = { prompt_tokens: 3, completion_tokens: 1, total_tokens: 4, input_tokens: 3, output_tokens: 1, ...(served ? { cost: 1.2e-05 } : {}) };
  if (path.endsWith("/chat/completions")) {
    return { id: "made-up", object: "chat.completion", created: 1, model, usage,
      choices: [{ index: 0, finish_reason: "stop", message: { role: "assistant", content: text } }] };
  }
  if (path.endsWith("/responses")) {
    return { id: "made-up", object: "response", created_at: 1, status: "completed", model, usage,
      output: [{ type: "message", id: "msg-made-up", status: "completed", role: "assistant", content: [{ type: "output_text", text, annotations: [] }] }] };
  }
  if (path.endsWith("/messages") || path.endsWith("/invoke")) {
    return { id: "made-up", type: "message", role: "assistant", model, content: [{ type: "text", text }], stop_reason: "end_turn", stop_sequence: null, usage };
  }
  if (path.endsWith("enerateContent")) {
    return { responseId: "made-up", modelVersion: model, candidates: [{ content: { role: "model", parts: [{ text }] }, finishReason: "STOP" }],
      usageMetadata: { promptTokenCount: 3, candidatesTokenCount: 1, totalTokenCount: 4 } };
  }
  if (path.endsWith("/converse")) {
    return { output: { message: { role: "assistant", content: [{ text }] } }, stopReason: "end_turn", usage: { inputTokens: 3, outputTokens: 1, totalTokens: 4 }, metrics: { latencyMs: 1 } };
  }
  return null;
}

/** Reflexer and the providers, as one place every call of a block reaches: each call, and whether it was a message call. */
const world = { /** @type {{ url: URL, headers: Headers, body: string, message: boolean }[]} */ seen: [] };

/** @param {URL} url @param {Headers} headers @param {any} sent @returns {{ status: number, headers: Record<string, string>, body: string }} */
function far(url, headers, sent) {
  const ours = url.host === check.REFLEXER;
  const body = answer(url.pathname, ours ? TEXT.served : TEXT.straight, ours);
  const text = sent == null || typeof sent === "string" ? sent ?? "" : ArrayBuffer.isView(sent) ? new TextDecoder().decode(sent) : `(a body not read: ${sent})`;
  world.seen.push({ url, headers, body: text, message: Boolean(body) });
  if (!ours && !/(^|\.)(openai\.com|anthropic\.com|googleapis\.com|azure\.com|amazonaws\.com)$/.test(url.hostname)) throw new TypeError(`offline: ${url.host}`);
  if (!body) return { status: 404, headers: {}, body: "" };
  const reflexers = ours ? { "reflexer-status-origin": "reflexer", "reflexer-answered-by": "reflexer", "reflexer-cost": "12000" } : {};
  return { status: 200, headers: { "content-type": "application/json", ...reflexers }, body: JSON.stringify(body) };
}

// This file runs in a process of its own: every `fetch`, and AWS JS's Node handlers, answer from the world, and stay so,
// so that a call a block leaves in flight reaches no one else
globalThis.fetch = async (input, init = {}) => {
  const url = new URL(input instanceof Request ? input.url : input);
  const { status, headers, body } = far(url, new Headers(init.headers ?? (input instanceof Request ? input.headers : undefined)), init.body);
  return new Response(body || null, { status, headers });
};
NodeHttpHandler.prototype.handle = NodeHttp2Handler.prototype.handle = async function handle(/** @type {any} */ request) {
  const url = new URL(`${request.protocol}//${request.hostname}${request.port ? `:${request.port}` : ""}${request.path}`);
  const { status, headers, body } = far(url, new Headers(Object.entries(request.headers).filter(([name]) => !name.startsWith(":"))), request.body);
  return { response: { statusCode: status, headers, body: Readable.from([Buffer.from(body)]) } };
};
// and no socket leaves this machine, whatever a library connects by
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (/** @type {any[]} */ ...args) {
  const [first, second] = Array.isArray(args[0]) ? args[0] : args; // `net.connect` hands its arguments on as one array
  const host = typeof first === "object" ? first.host ?? first.path : typeof second === "string" ? second : undefined;
  if (host && !/^(127\.|::1$|localhost$|\/)/.test(String(host))) throw new Error(`offline: ${host}`);
  return connect.apply(this, /** @type {any} */ (args));
};
const AMBIENT = /^(OPENAI_|ANTHROPIC_|GOOGLE_|GEMINI_|AZURE_|AWS_|HTTPS?_PROXY$|ALL_PROXY$|NO_PROXY$)/i; // nothing of the caller's reaches a block

/** Whether a framework a block imports needs a newer Node than this one: the AI SDK's and LangChain.js's floors are their own. @param {string} code */
async function tooNew(code) {
  for (const [, name] of code.matchAll(/from "((?:@[^/"]+\/)?[^/"]+)[^"]*"/g)) {
    if (!/^(ai$|@ai-sdk\/|@langchain\/)/.test(name)) continue;
    const engines = JSON.parse(await readFile(join(check.PACKAGE, "node_modules", name, "package.json"), "utf8")).engines?.node ?? "";
    if (Number(process.versions.node.split(".")[0]) < Number(/>=\s*(\d+)/.exec(engines)?.[1] ?? 0)) return `${name} needs Node ${engines}`;
  }
  return false;
}

/** The blocks of the docs: [where, marker words, code]. */
async function blocks() {
  const found = [];
  for (const path of DOCS) {
    const text = (await readFile(path, "utf8")).replaceAll("\r\n", "\n");
    for (const match of text.matchAll(BLOCK)) {
      found.push([`${path.slice(ROOT.length + 1)}:${text.slice(0, match.index).split("\n").length}`, (match[1] ?? "").split(" "), match[2]]);
    }
  }
  return found;
}

/**
 * `code` run as a module of its own, in the world above: what it printed, and every call. `way`: Bedrock's, "key" or
 * "signed", or null. Its folder, made inside the package so that `@reflexer-ai/sdk` resolves, is removed after.
 * @param {import("node:test").TestContext} t @param {string} code @param {string | null} way
 */
async function run(t, code, way) {
  const kept = { ...process.env };
  const folder = await mkdtemp(join(check.PACKAGE, ".docs-"));
  t.after(() => rm(folder, { recursive: true })); // after a timeout too
  t.after(() => { // in place: the process's own environment object stays
    for (const name of Object.keys(process.env)) if (!(name in kept)) delete process.env[name];
    Object.assign(process.env, kept);
  });
  /** @type {string[]} */
  const printed = [];
  world.seen = [];
  t.mock.method(console, "log", (/** @type {any[]} */ ...values) => {
    printed.push(format(...values));
    if (values.some((value) => value == null || Number.isNaN(value))) printed.push("(a value printed is missing)");
  });
  t.mock.method(console, "warn", () => {});
  t.mock.method(Math, "random", () => 0.5);
  for (const name of Object.keys(process.env).filter((name) => AMBIENT.test(name))) delete process.env[name];
  Object.assign(process.env, ENVIRONMENT, way === "key" ? { AWS_BEARER_TOKEN_BEDROCK: BEARER } : {});
  await writeFile(join(folder, "example.mjs"), code);
  await import(pathToFileURL(join(folder, "example.mjs")).href);
  return { printed: printed.join("\n"), seen: world.seen };
}

/** Whether what a block printed, and what reached where, is what its comment says. @param {any} ran @param {string} outcome @param {string | null} way */
function judge({ printed, seen }, outcome, way) {
  assert.ok(!printed.includes("(a value printed is missing)"), `a value printed is missing: ${printed}`);
  const answers = outcome === "served" ? [TEXT.served] : [TEXT.straight];
  const given = Object.values(TEXT).filter((text) => printed.includes(text));
  assert.ok(given.length && given.every((text) => answers.includes(text)), `each answer printed must be ${outcome}: ${printed}`);
  const count = given.reduce((sum, text) => sum + printed.split(text).length - 1, 0);
  const calls = seen.filter((/** @type {any} */ call) => call.message);
  assert.ok(count >= calls.length, `an answer printed for each call: ${printed}`);
  const reached = calls.filter(({ url }) => url.host === check.REFLEXER);
  if (outcome === "straight") assert.deepEqual(reached.map(({ url }) => url.pathname), [], "reflexer got the call");
  if (way) {
    const bedrock = calls.filter(({ url }) => url.pathname.startsWith("/bedrock/") || url.hostname.endsWith("amazonaws.com"));
    const schemes = [...new Set(bedrock.map(({ headers }) => (headers.get("authorization") ?? "").split(" ")[0]))];
    assert.deepEqual(schemes, [WAYS[/** @type {keyof WAYS} */ (way)]], `a Bedrock call not made the way asked: ${schemes}`);
  }
  const keyed = seen.filter(({ url, headers, body }) => url.host !== check.REFLEXER && `${[...headers.values()]} ${url.href} ${body}`.includes(key));
  assert.deepEqual(keyed.map(({ url }) => url.host), [], "the reflexer key reached a provider");
}

describe("The docs' examples", async () => {
  const found = await blocks();
  test("there are some", () => assert.ok(found.length));
  for (const [where, words, code] of found) {
    for (const way of words.includes("bedrock") ? Object.keys(WAYS) : [null]) {
      test(`${where}${way ? ` (Bedrock, ${way})` : ""}`, { skip: await tooNew(code), timeout: LIMIT }, async (t) => {
        assert.ok(["served", "straight"].includes(words[0]) && words.slice(1).every((word) => word === "bedrock"), "no <!-- example: ... --> it knows");
        judge(await run(t, code, way), words[0], way);
      });
    }
  }
});

describe("A planted fault turns it red", () => {
  const call = 'client.chat.completions.create({ model: "m", messages: [] })';
  const text = `(await ${call}).choices[0].message.content`;
  const ours = 'import { OpenAI } from "@reflexer-ai/sdk/openai";\nconst client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY });';
  const stock = 'import OpenAI from "openai";\nconst client = new OpenAI();';
  const converse = 'const answer = await client.send(new ConverseCommand({ modelId: "m", messages: [{ role: "user", content: [{ text: "Hi" }] }] }));';
  const aws = `import { BedrockRuntimeClient, ConverseCommand } from "@aws-sdk/client-bedrock-runtime";
import * as bedrock from "@reflexer-ai/sdk/bedrock";
const client = bedrock.wrap(new BedrockRuntimeClient({ region: "us-east-1" }), process.env.REFLEXER_KEY);`;
  /** name: [outcome, code, Bedrock's way, the check that must fail] */
  const PLANTED = {
    "a stock client, said to be served": ["served", `${stock}\nconsole.log(${text});`, null, /must be served/],
    "an answer not printed": ["served", `${ours}\nawait ${call};\nconsole.log(${text});`, null, /an answer printed for each call/],
    "a call to reflexer, said to go straight": ["straight", `${ours}\nconsole.log(${text}.replace("served by reflexer", "from the provider"));`, null,
      /reflexer got the call/],
    "the reflexer key sent to a provider": ["straight", `${stock}\nconsole.log((await client.withOptions({ defaultHeaders: { "x-made-up": process.env.REFLEXER_KEY } }).chat.completions.create({ model: "m", messages: [] })).choices[0].message.content);`,
      null, /the reflexer key reached a provider/],
    "a Bedrock key where a signed call is said": ["served", `process.env.AWS_BEARER_TOKEN_BEDROCK = "${BEARER}";\n${aws}\n${converse}\nconsole.log(answer.output.message.content[0].text);`,
      "signed", /not made the way asked/],
    "a call said to be Bedrock's, but not": ["served", `${ours}\nconsole.log(${text});`, "key", /not made the way asked/],
    "a value missing": ["served", `${ours}\nconsole.log(${text}, (await ${call}).usage.cots);`, null, /a value printed is missing/],
    "a socket off this machine": ["served", 'import net from "node:net";\nnet.connect({ host: "192.0.2.1", port: 80 });', null, /offline/],
    "a share that has no effect": ["straight", `import { OpenAI } from "@reflexer-ai/sdk/openai";\nconst client = new OpenAI({ reflexerKey: process.env.REFLEXER_KEY, sample: 0.9 });\nconsole.log(${text});`,
      null, /must be straight/],
  };
  for (const [name, [outcome, code, way, failure]] of Object.entries(PLANTED)) {
    test(name, { timeout: LIMIT }, async (t) => assert.rejects(async () => judge(await run(t, String(code), /** @type {any} */ (way)), String(outcome), /** @type {any} */ (way)), failure));
  }
});

// The package's static promises, and a planted fault for each that shows its gate can fail. Offline.
import * as acorn from "acorn";
import * as walk from "acorn-walk";
import * as scope from "eslint-scope";
import assert from "node:assert/strict";
import { cp, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, describe, test } from "node:test";
import { PACKAGE } from "./checks.js";

/** What each file may import: Node's built-ins that open no socket and run no process, and a provider's SDK in its own file. */
const ALLOWED = {
  "logic.js": ["node:crypto"],
  "index.js": ["./logic.js"],
  "bedrock.js": ["./index.js", "./logic.js", "node:async_hooks"], // async_hooks: a call's own state, set by our middleware for our fetch
  "openai.js": ["openai", "openai/version", "./index.js"],
  "anthropic.js": ["@anthropic-ai/sdk", "@anthropic-ai/sdk/version", "./index.js"],
  "gemini.js": ["@google/genai", "./index.js"],
};
// The globals the source may read, and of some only these members: none reaches a module, a process, a socket, or code made from text
const GLOBALS = new Map(Object.entries({
  AbortController: null, AbortSignal: ["any", "timeout"], Array: null, ArrayBuffer: null, BigInt: null, DOMException: null, Error: null, Headers: null,
  JSON: ["parse"], Math: null, Number: null, Object: ["defineProperty", "entries", "fromEntries", "hasOwn", "keys"], RegExp: null,
  Request: null, String: null, Symbol: ["for"], TextDecoder: null, TypeError: null, URL: null, WeakMap: null, clearTimeout: null,
  console: null, globalThis: ["fetch"], parseInt: null, performance: null, setTimeout: null, undefined: null,
}));
const DISPATCHER = 'Symbol.for("undici.globalDispatcher.1")'; // the one member of `globalThis` reached by a computed name
const REFUSED = new Set(["constructor", "prototype", "__proto__"]); // a way from a value to the code that made it

/** @param {string} root */
async function sources(root) {
  const names = (await readdir(join(root, "src"))).filter((name) => name.endsWith(".js")).sort();
  return Promise.all(names.map(async (name) => ({ name, text: await readFile(join(root, "src", name), "utf8") })));
}

/** @param {string} text */
const parse = (text) => acorn.parse(text, { ecmaVersion: "latest", sourceType: "module", locations: true, ranges: true });

/** @param {string} root */
async function manifest(root) {
  return JSON.parse(await readFile(join(root, "package.json"), "utf8"));
}

/** What the package makes its client install: its dependencies, and its peers not optional. @param {string} root */
async function dependencies(root) {
  const { dependencies = {}, peerDependencies = {}, peerDependenciesMeta = {} } = await manifest(root);
  return [...Object.keys(dependencies), ...Object.keys(peerDependencies).filter((name) => !peerDependenciesMeta[name]?.optional)];
}

/**
 * Each file's imports outside its allowlist, and each way around it: a dynamic import, a global not listed or a member of
 * it not listed (a bare `fetch`, `global`, `process`, `Reflect`, `Function`, `Object.getPrototypeOf`), a member reached by
 * a name computed at run time but Node's dispatcher, written in place, or a way to the code that made a value. Globals are
 * the names no scope declares, as eslint-scope reads them.
 * @param {string} root
 */
async function importsNotAllowed(root) {
  const found = [];
  for (const { name, text } of await sources(root)) {
    const allowed = /** @type {Record<string, string[]>} */ (ALLOWED)[name];
    if (!allowed) {
      found.push(`${name}: a file with no import allowlist`);
      continue;
    }
    const tree = parse(text), parents = new Map();
    walk.fullAncestor(tree, (/** @type {any} */ node, _, /** @type {any[]} */ ancestors) => {
      parents.set(node, ancestors[ancestors.length - 2]);
      if (node.type.endsWith("Declaration") && node.source && !allowed.includes(node.source.value)) found.push(`${name}: ${node.source.value}`);
      if (node.type === "ImportExpression" || node.type === "MetaProperty") found.push(`${name}: a dynamic import`);
      if (node.type === "Literal" && REFUSED.has(node.value)) found.push(`${name}: ${node.value}`);
      if (node.type === "MemberExpression" && !node.computed && REFUSED.has(node.property.name)) found.push(`${name}: ${node.property.name}`);
      if (node.type === "MemberExpression" && node.computed && node.property.type !== "Literal"
        && !(node.object.name === "globalThis" && text.slice(node.property.start, node.property.end) === DISPATCHER)) {
        found.push(`${name}: a member by a computed name`);
      }
    });
    const { globalScope } = scope.analyze(/** @type {any} */ (tree), { ecmaVersion: 2022, sourceType: "module" });
    const module = new Set(globalScope?.childScopes[0]?.set.keys()); // its own, read as global where an `eval` could change them
    for (const { identifier } of (globalScope?.through ?? []).filter(({ identifier }) => !module.has(identifier.name))) {
      const parent = parents.get(identifier), members = GLOBALS.get(identifier.name);
      const member = parent?.type === "MemberExpression" && parent.object === identifier
        ? (parent.computed ? text.slice(parent.property.start, parent.property.end) : parent.property.name) : undefined;
      if (members === undefined) found.push(`${name}: ${identifier.name}`);
      else if (members && !(members.includes(member) || (identifier.name === "globalThis" && member === DISPATCHER))) {
        found.push(`${name}: ${identifier.name}${member === undefined ? "" : `.${member}`}`);
      }
    }
  }
  return found;
}

/**
 * lines: lines holding code, with no comment. ifs: `if`, a conditional expression, `case`. privateNames: another's `_names`.
 * `files`: those measured, else every file; `but`: those left out.
 * @param {string} root @param {{ files?: string[], but?: string[] }} [which]
 */
async function measure(root, { files, but = [] } = {}) {
  let lines = 0, ifs = 0;
  const defined = new Set(), read = new Set();
  for (const { text } of (await sources(root)).filter(({ name }) => (!files || files.includes(name)) && !but.includes(name))) {
    const held = new Set();
    for (const token of acorn.tokenizer(text, { ecmaVersion: "latest", sourceType: "module", locations: true })) {
      for (let line = token.loc?.start.line ?? 0; line <= (token.loc?.end.line ?? -1); line++) held.add(line);
    }
    lines += held.size;
    walk.full(parse(text), (/** @type {any} */ node) => {
      if (["IfStatement", "ConditionalExpression", "SwitchCase"].includes(node.type)) ifs++;
      if (["MethodDefinition", "PropertyDefinition"].includes(node.type)) defined.add(node.key.name);
      if (node.type === "MemberExpression") read.add(node.computed ? node.property.value : node.property.name);
    });
  }
  const privateNames = [...read].filter((name) => /^_[^_]/.test(name ?? "") && !defined.has(name)).sort();
  return { lines, ifs, privateNames };
}

/**
 * What exceeds the budgets in package.json, as text; empty when within them: every file but Bedrock's against the
 * package's, Bedrock's (`bedrock.files`) against its own, so an audit of another provider's path reads none of them.
 * @param {string} root
 */
async function overBudget(root) {
  const { reflexer: { budget: { bedrock, ...budget } } } = await manifest(root);
  /** @param {Record<string, number>} limits @param {any} size @param {string} label */
  const over = (limits, size, label) => {
    /** @type {Record<string, number>} */
    const found = { lines: size.lines, ifs: size.ifs, privateNames: size.privateNames.length };
    return Object.keys(limits).filter((name) => name in found && found[name] > limits[name]).map((name) => `${label}${name}: ${found[name]}, budget ${limits[name]}`);
  };
  const { files, ...apart } = bedrock ?? { files: [] };
  return [...over(budget, await measure(root, { but: files }), ""), ...over(apart, await measure(root, { files }), "bedrock ")];
}

describe("Gates", () => {
  test("no dependency", async () => {
    assert.deepEqual(await dependencies(PACKAGE), []);
  });

  test("the package's name is in the scope of the repository's organisation", async () => {
    assert.equal((await manifest(PACKAGE)).name, "@reflexer-ai/sdk");
  });

  test("imports are allowed", async () => {
    assert.deepEqual(await importsNotAllowed(PACKAGE), []);
  });

  test("within budget", async (t) => {
    const { reflexer: { budget: { bedrock } } } = await manifest(PACKAGE);
    const size = await measure(PACKAGE, { but: bedrock.files }), apart = await measure(PACKAGE, { files: bedrock.files });
    t.diagnostic(`lines ${size.lines}, ifs ${size.ifs}, private names ${size.privateNames.length}; Bedrock's: lines ${apart.lines}, ifs ${apart.ifs}`);
    assert.deepEqual(await overBudget(PACKAGE), []);
  });
});

describe("Broken", () => {
  let root = "";
  const FAULTS = join(tmpdir(), "reflexer-gates-");
  before(async () => {
    root = await mkdtemp(FAULTS);
  });
  after(async () => {
    assert.ok(root.startsWith(FAULTS), root); // only the folder made above
    await rm(root, { recursive: true });
  });

  /** A copy of the package with `text` added to `file`, or to the manifest with `manifest`. */
  async function plant(/** @type {string} */ file, /** @type {string} */ text) {
    await rm(join(root, "copy"), { recursive: true, force: true });
    await cp(join(PACKAGE, "src"), join(root, "copy", "src"), { recursive: true });
    await cp(join(PACKAGE, "package.json"), join(root, "copy", "package.json"));
    const path = join(root, "copy", file);
    await writeFile(path, (await readFile(path, "utf8").catch(() => "")) + `\n${text}\n`);
    return join(root, "copy");
  }

  /** A copy whose manifest is edited by `edit`. @param {(manifest: any) => void} edit */
  async function manifestEdited(edit) {
    const copy = await plant("src/index.js", "");
    const data = await manifest(copy);
    edit(data);
    await writeFile(join(copy, "package.json"), JSON.stringify(data));
    return copy;
  }

  test("a dependency turns it red", async () => {
    const copy = await manifestEdited((data) => { data.dependencies = { "made-up": "1.0.0" }; });
    assert.deepEqual(await dependencies(copy), ["made-up"]);
  });

  test("a peer not optional turns it red", async () => {
    const copy = await manifestEdited((data) => { delete data.peerDependenciesMeta.openai; });
    assert.deepEqual(await dependencies(copy), ["openai"]);
  });

  test("an import outside the allowlist turns it red", async () => {
    assert.deepEqual(await importsNotAllowed(await plant("src/logic.js", 'import "node:net";')), ["logic.js: node:net"]);
    assert.deepEqual(await importsNotAllowed(await plant("src/index.js", 'export * from "node:child_process";')), ["index.js: node:child_process"]);
  });

  test("a file with no allowlist turns it red", async () => {
    assert.deepEqual(await importsNotAllowed(await plant("src/made-up.js", "")), ["made-up.js: a file with no import allowlist"]);
  });

  test("a way around the allowlist turns it red", async () => {
    for (const [text, ...problems] of [
      ["const made = (/** @type {string} */ name) => import(name);", "a dynamic import"],
      ["const made = import.meta.resolve;", "a dynamic import"],
      ['const made = fetch("https://made-up.example/x");', "fetch"],
      ['const made = process.binding("tcp_wrap");', "process"],
      ['const made = global.process.getBuiltinModule("child_process");', "global"],
      ["const made = globalThis.process;", "globalThis.process"],
      ['const made = globalThis["pro" + "cess"];', "a member by a computed name", 'globalThis."pro" + "cess"'],
      ['const made = Reflect.get(Object.getPrototypeOf(() => {}), "constr" + "uctor")("return 1");', "Reflect", "Object.getPrototypeOf"],
      ['const made = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(() => {}), "constructor");', "constructor",
        "Object.getOwnPropertyDescriptor", "Object.getPrototypeOf"],
      ['const made = eval("1");', "eval"],
      ['const made = new Function("return 1");', "Function"],
      ['const made = (() => {}).constructor("return 1");', "constructor"],
      ['const made = new WebSocket("wss://made-up.example");', "WebSocket"],
      ["const made = (process) => process;\nexport const other = () => process.version;", "process"], // a name trusted in one scope only
      ['const DISPATCHER = "pro" + "cess";\nexport const made = globalThis[DISPATCHER];', "a member by a computed name", "globalThis.DISPATCHER"],
      ["const made = Object.values(Object.getOwnPropertyDescriptors(Object.getPrototypeOf(() => {})));",
        "Object.values", "Object.getOwnPropertyDescriptors", "Object.getPrototypeOf"],
    ]) {
      assert.deepEqual(await importsNotAllowed(await plant("src/logic.js", text)), problems.map((problem) => `logic.js: ${problem}`), text);
    }
  });

  test("growth past budget turns it red", async () => {
    const copy = await plant("src/logic.js", Array.from({ length: 400 }, (_, n) => `export const made${n} = n ? 1 : 0;`).join("\n"));
    assert.deepEqual((await overBudget(copy)).map((problem) => problem.split(":")[0]), ["lines", "ifs"]);
  });

  test("growth in a shared file is not Bedrock's to hold", async () => {
    const shared = await plant("src/logic.js", Array.from({ length: 10 }, (_, n) => `export const made${n} = n ? 1 : 0;`).join("\n"));
    assert.deepEqual((await overBudget(shared)).map((problem) => problem.split(":")[0]), ["lines", "ifs"]);
    const apart = await plant("src/bedrock.js", Array.from({ length: 10 }, (_, n) => `export const made${n} = n ? 1 : 0;`).join("\n"));
    assert.deepEqual((await overBudget(apart)).map((problem) => problem.split(":")[0]), ["bedrock lines", "bedrock ifs"]);
  });

  test("another's private name turns it red", async () => {
    const copy = await plant("src/logic.js", "export const made = (/** @type {any} */ other) => other._madeUpPrivate;");
    assert.deepEqual((await measure(copy)).privateNames, ["_madeUpPrivate"]);
    assert.deepEqual(await overBudget(copy), ["privateNames: 1, budget 0"]);
  });
});

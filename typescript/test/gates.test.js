// The package's static promises, and a planted fault for each that shows its gate can fail. Offline.
import * as acorn from "acorn";
import * as walk from "acorn-walk";
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
  "openai.js": ["openai", "./index.js"],
  "anthropic.js": ["@anthropic-ai/sdk", "./index.js"],
  "gemini.js": ["@google/genai", "./index.js"],
};
// Ways around the allowlist: to a module, a process, a socket or code made from text
const BANNED = new Set(["require", "module", "process", "eval", "Function", "WebAssembly", "WebSocket", "EventSource", "Deno", "Bun"]);

/** @param {string} root */
async function sources(root) {
  const names = (await readdir(join(root, "src"))).filter((name) => name.endsWith(".js")).sort();
  return Promise.all(names.map(async (name) => ({ name, text: await readFile(join(root, "src", name), "utf8") })));
}

/** @param {string} text */
const parse = (text) => acorn.parse(text, { ecmaVersion: "latest", sourceType: "module", locations: true });

/** @param {string} root */
async function manifest(root) {
  return JSON.parse(await readFile(join(root, "package.json"), "utf8"));
}

/** What the package makes its client install: its dependencies, and its peers not optional. @param {string} root */
async function dependencies(root) {
  const { dependencies = {}, peerDependencies = {}, peerDependenciesMeta = {} } = await manifest(root);
  return [...Object.keys(dependencies), ...Object.keys(peerDependencies).filter((name) => !peerDependenciesMeta[name]?.optional)];
}

/** @param {string} root */
async function importsNotAllowed(root) {
  const found = [];
  for (const { name, text } of await sources(root)) {
    const allowed = /** @type {Record<string, string[]>} */ (ALLOWED)[name];
    if (!allowed) {
      found.push(`${name}: a file with no import allowlist`);
      continue;
    }
    walk.fullAncestor(parse(text), (/** @type {any} */ node, _, /** @type {any[]} */ ancestors) => {
      const parent = ancestors[ancestors.length - 2];
      if (node.type.endsWith("Declaration") && node.source && !allowed.includes(node.source.value)) found.push(`${name}: ${node.source.value}`); // import, export from
      if (node.type === "ImportExpression" || node.type === "MetaProperty") found.push(`${name}: a dynamic import`);
      if (node.type === "Identifier" && BANNED.has(node.name)) found.push(`${name}: ${node.name}`);
      if (node.type === "Identifier" && node.name === "globalThis"
        && !(parent?.type === "MemberExpression" && !parent.computed && parent.property.name === "fetch")) found.push(`${name}: globalThis`);
      if (node.type === "MemberExpression" && (node.computed ? node.property.value : node.property.name) === "constructor") {
        found.push(`${name}: a constructor reached`);
      }
    });
  }
  return found;
}

/** lines: lines holding code, with no comment. ifs: `if`, a conditional expression, `case`. privateNames: another's `_names`. */
async function measure(/** @type {string} */ root) {
  let lines = 0, ifs = 0;
  const defined = new Set(), read = new Set();
  for (const { text } of await sources(root)) {
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

/** What exceeds the budget in package.json, as text; empty when within it. @param {string} root */
async function overBudget(root) {
  const { reflexer: { budget } } = await manifest(root);
  const size = await measure(root);
  /** @type {Record<string, number>} */
  const found = { lines: size.lines, ifs: size.ifs, privateNames: size.privateNames.length };
  return Object.keys(budget).filter((name) => found[name] > budget[name]).map((name) => `${name}: ${found[name]}, budget ${budget[name]}`);
}

describe("Gates", () => {
  test("no dependency", async () => {
    assert.deepEqual(await dependencies(PACKAGE), []);
  });

  test("imports are allowed", async () => {
    assert.deepEqual(await importsNotAllowed(PACKAGE), []);
  });

  test("within budget", async (t) => {
    const size = await measure(PACKAGE);
    t.diagnostic(`lines ${size.lines}, ifs ${size.ifs}, private names ${size.privateNames.length}`);
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
    for (const [text, problem] of [
      ['const made = (/** @type {string} */ name) => import(name);', "a dynamic import"],
      ["const made = import.meta.resolve;", "a dynamic import"],
      ['const made = process.binding("tcp_wrap");', "process"],
      ['const made = globalThis["pro" + "cess"];', "globalThis"],
      ["const made = globalThis.process;", "globalThis"],
      ['const made = eval("1");', "eval"],
      ['const made = (() => {}).constructor("return 1");', "a constructor reached"],
      ['const made = new WebSocket("wss://made-up.example");', "WebSocket"],
    ]) {
      assert.deepEqual(await importsNotAllowed(await plant("src/logic.js", text)), [`logic.js: ${problem}`], text);
    }
  });

  test("growth past budget turns it red", async () => {
    const copy = await plant("src/logic.js", Array.from({ length: 400 }, (_, n) => `export const made${n} = n ? 1 : 0;`).join("\n"));
    assert.deepEqual((await overBudget(copy)).map((problem) => problem.split(":")[0]), ["lines", "ifs"]);
  });

  test("another's private name turns it red", async () => {
    const copy = await plant("src/logic.js", "export const made = (/** @type {any} */ other) => other._madeUpPrivate;");
    assert.deepEqual((await measure(copy)).privateNames, ["_madeUpPrivate"]);
    assert.deepEqual(await overBudget(copy), ["privateNames: 1, budget 0"]);
  });
});

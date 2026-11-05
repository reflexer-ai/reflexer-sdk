// What the drift run tests: each provider SDK and Bedrock library the source names, one `name newest-major floor` line each, read from the
// module, not its text; it fails when that list is not the package's peers, one for one. Run: node tools/tested.js
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { LIBRARIES } from "../src/bedrock.js";
import { SDKS } from "../src/index.js";

/** Each library the source names once: the provider SDKs, and Bedrock's (AnthropicBedrock's calls name the SDK it is built on). */
export const NAMED = [...SDKS, ...LIBRARIES.filter(({ name }) => !SDKS.some((sdk) => sdk.name === name))];

/** @param {{ name: string, majors: number[], floor: string }[]} sdks @param {string[]} peers */
export function lines(sdks, peers) {
  const names = sdks.map(({ name }) => name).sort();
  if (names.join() !== [...peers].sort().join()) throw new Error(`the source names ${names.join(", ")}; the package's peers are ${peers.join(", ")}`);
  return sdks.map(({ name, majors, floor }) => `${name} ${Math.max(...majors)} ${floor}`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const { peerDependencies } = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  console.log(lines(NAMED, Object.keys(peerDependencies)).join("\n"));
}

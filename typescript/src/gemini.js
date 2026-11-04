/**
 * @google/genai's own client, through reflexer: `new GoogleGenAI(config)` becomes `new GoogleGenAI({ ...config, reflexerKey })`,
 * imported from here; or, on the stock class, `new GoogleGenAI({ ...config, httpOptions: { fetch: reflexer.gemini.fetch(reflexerKey) } })`.
 * Its `fetch` sits in `httpOptions`, and it makes no copies of a client. It exports no version: its user agent names it, on each call.
 */
import * as stock from "@google/genai";
import { BASE, gemini, supported } from "./index.js";

export class GoogleGenAI extends stock.GoogleGenAI {
  /** @param {stock.GoogleGenAIOptions & { reflexerKey: string, reflexerBase?: string, sample?: number }} options */
  constructor({ reflexerKey, reflexerBase = BASE, sample = 1, httpOptions = {}, ...config }) {
    const routed = gemini.fetch(reflexerKey, { base: reflexerBase, sample, fetch: httpOptions.fetch });
    /** @type {typeof routed} */
    const checked = (input, init) => {
      const version = /google-genai-sdk\/([0-9.]+)/.exec(new Headers(init?.headers).get("user-agent") ?? "");
      if (version) supported("@google/genai", version[1], [2]);
      return routed(input, init);
    };
    super({ ...config, httpOptions: { ...httpOptions, fetch: checked } });
  }
}

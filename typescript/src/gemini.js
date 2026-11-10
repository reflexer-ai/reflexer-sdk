/**
 * @google/genai's own client, through reflexer: `new GoogleGenAI(config)` becomes `new GoogleGenAI({ ...config, reflexerKey })`,
 * imported from here; or, on the stock class, `new GoogleGenAI({ ...config, httpOptions: { fetch: reflexer.gemini.fetch(reflexerKey) } })`.
 * Its `fetch` sits in `httpOptions`, and it makes no copies of a client. It exports no version: its calls name it, in their user agent.
 */
import * as stock from "@google/genai";
import { BASE, gemini, tested } from "./index.js";

export class GoogleGenAI extends stock.GoogleGenAI {
  /** @param {stock.GoogleGenAIOptions & { reflexerKey: string, reflexerBase?: string, sample?: number, reflexerNamespace?: string }} options */
  constructor({ reflexerKey, reflexerBase = BASE, sample = 1, reflexerNamespace, httpOptions = {}, ...config }) {
    const routed = gemini.fetch(reflexerKey, { base: reflexerBase, sample, namespace: reflexerNamespace, fetch: httpOptions.fetch });
    /** @type {typeof routed} */
    const checked = (input, init) => {
      if (!tested(new Headers(init?.headers)).includes("@google/genai")) throw new Error("reflexer cannot find google-genai's version: its calls do not state it");
      return routed(input, init);
    };
    super({ ...config, httpOptions: { ...httpOptions, fetch: checked } });
  }
}

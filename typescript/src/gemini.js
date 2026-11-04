/**
 * @google/genai's own client, through reflexer: `new GoogleGenAI(config)` becomes `new GoogleGenAI({ ...config, reflexerKey })`,
 * imported from here; or, on the stock class, `new GoogleGenAI({ ...config, httpOptions: { fetch: reflexer.gemini.fetch(reflexerKey) } })`.
 * Its `fetch` sits in `httpOptions`, and it makes no copies of a client.
 */
import * as stock from "@google/genai";
import { BASE, gemini } from "./index.js";

export class GoogleGenAI extends stock.GoogleGenAI {
  /** @param {stock.GoogleGenAIOptions & { reflexerKey: string, reflexerBase?: string, sample?: number }} options */
  constructor({ reflexerKey, reflexerBase = BASE, sample = 1, httpOptions = {}, ...config }) {
    const fetch = gemini.fetch(reflexerKey, { base: reflexerBase, sample, fetch: httpOptions.fetch });
    super({ ...config, httpOptions: { ...httpOptions, fetch } });
  }
}

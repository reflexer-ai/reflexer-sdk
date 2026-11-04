/**
 * openai's own clients, through reflexer: `new OpenAI(config)` becomes `new OpenAI({ ...config, reflexerKey })`, imported
 * from here; or, on the stock class, `new OpenAI({ ...config, fetch: reflexer.openai.fetch(reflexerKey) })`.
 */
import * as stock from "openai";
import { WIRES, client } from "./index.js";

export const OpenAI = client(stock.OpenAI, WIRES.openai);
export const AzureOpenAI = client(stock.AzureOpenAI, WIRES.azure);

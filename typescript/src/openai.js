/**
 * openai's own clients, through reflexer: `new OpenAI(config)` becomes `new OpenAI({ ...config, reflexerKey })`, imported
 * from here; or, on the stock class, `new OpenAI({ ...config, fetch: reflexer.openai.fetch(reflexerKey) })`.
 */
import * as stock from "openai";
import { VERSION } from "openai/version";
import { WIRES, client, supported } from "./index.js";

supported("openai", VERSION);

export const OpenAI = client(stock.OpenAI, WIRES.openai);
export const AzureOpenAI = client(stock.AzureOpenAI, WIRES.azure);

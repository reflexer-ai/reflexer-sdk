/**
 * @anthropic-ai/sdk's own client, through reflexer: `new Anthropic(config)` becomes `new Anthropic({ ...config, reflexerKey })`,
 * imported from here; or, on the stock class, `new Anthropic({ ...config, fetch: reflexer.anthropic.fetch(reflexerKey) })`.
 */
import * as stock from "@anthropic-ai/sdk";
import { WIRES, client } from "./index.js";

export const Anthropic = client(stock.Anthropic, WIRES.anthropic);

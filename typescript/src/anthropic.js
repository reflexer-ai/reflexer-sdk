/**
 * @anthropic-ai/sdk's own client, through reflexer: `new Anthropic(config)` becomes `new Anthropic({ ...config, reflexerKey })`,
 * imported from here; or, on the stock class, `new Anthropic({ ...config, fetch: reflexer.anthropic.fetch(reflexerKey) })`.
 * Its own timeout at reflexer sends the call straight, by `client`'s middleware.
 */
import * as stock from "@anthropic-ai/sdk";
import { VERSION } from "@anthropic-ai/sdk/version";
import { WIRES, client, supported } from "./index.js";

supported("@anthropic-ai/sdk", VERSION);

export const Anthropic = client(stock.Anthropic, WIRES.anthropic, { middleware: true });

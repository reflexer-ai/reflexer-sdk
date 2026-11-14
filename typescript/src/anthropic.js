/**
 * @anthropic-ai/sdk's own client, through reflexer: `new Anthropic(config)` becomes `new Anthropic({ ...config, reflexerKey })`,
 * imported from here; or, on the stock class, `new Anthropic({ ...config, fetch: reflexer.anthropic.fetch(reflexerKey) })`.
 */
import * as stock from "@anthropic-ai/sdk";
import { VERSION } from "@anthropic-ai/sdk/version";
import { SKIP, WIRES, client, cutAtReflexer, supported } from "./index.js";

supported("@anthropic-ai/sdk", VERSION);

/**
 * The class's own middleware, after the client's. The SDK arms its timeout around each inner fetch and cuts with no
 * reason, as a cancel does; this middleware, above that timer, sees the client's own signal (`ctx.options.signal`):
 * reflexer's leg cut while it is not aborted was cut by the timer, so `next` again, straight, with the client's timeout
 * afresh, to the answer's start as the SDK's own, and its cancel kept. Streamed too: its caller still waits.
 * @param {any} request @param {any} next @param {any} ctx
 */
async function afterTimeout(request, next, ctx) {
  try {
    return await next(request);
  } catch (failure) {
    const options = ctx?.options ?? {};
    if (!cutAtReflexer(request.signal) || options.signal?.aborted || !options.timeout) throw failure;
    const late = new AbortController();
    const clock = setTimeout(() => late.abort(), options.timeout); // no reason, as the SDK's own timer
    try {
      const headers = new Headers(request.headers);
      headers.set(SKIP, "true"); // straight: the line takes it off
      return await next({ ...request, headers, signal: AbortSignal.any([late.signal, options.signal].filter((signal) => signal)) });
    } finally {
      clearTimeout(clock);
    }
  }
}

const Reflexed = client(stock.Anthropic, WIRES.anthropic);

// @ts-ignore: a mixin's constructor takes the stock options, and ours
class Client extends Reflexed {
  /** @param {any} options */
  constructor(options = {}) {
    const own = options.middleware ?? [];
    super({ ...options, middleware: own.includes(afterTimeout) ? own : [...own, afterTimeout] }); // a copy is given ours back
  }
}

Object.defineProperty(Client, "name", { value: stock.Anthropic.name }); // the SDK names its client by it, in its user agent
export const Anthropic = /** @type {typeof Reflexed} */ (/** @type {any} */ (Client));

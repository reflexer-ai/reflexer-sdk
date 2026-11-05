// The scene `Promises::an error thrown to the client shows the key in no frame of the SDK's` watches, in a process of its
// own under the inspector: errors the Bedrock lines throw to the client, a replay reflexer does not take, by AWS JS's
// handler and by the fetch line. `node frames-scene.js PACKAGE`; every value made up.
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const root = process.argv[2];
const bedrock = await import(pathToFileURL(join(root, "src", "bedrock.js")).href);
const { checksum } = await import(pathToFileURL(join(root, "src", "index.js")).href);
const secret = "rfx1_aaaaakq_" + "a".repeat(52);
const key = `${secret}_${checksum(secret)}`;
const replay = JSON.stringify({ messages: [], replay_response: { id: "made-up" } });
const busy = { "reflexer-status-origin": "reflexer", "retry-after": "0" };
const handler = {
  metadata: { handlerProtocol: "h2" },
  handle: async (/** @type {any} */ request) => ({ response: { statusCode: request.hostname.includes("reflexer") ? 503 : 200,
    headers: request.hostname.includes("reflexer") ? busy : {}, body: undefined } }),
};
const headers = { authorization: "Bearer ABSK-made-up", "content-type": "application/json" };
const thrown = [];
await bedrock.requestHandler(key, { handler }).handle({ method: "POST", protocol: "https:", hostname: "bedrock-runtime.us-east-1.amazonaws.com",
  path: "/model/m/invoke", query: {}, headers, body: replay }).catch((/** @type {any} */ failure) => thrown.push(failure.name));
const fetch = async (/** @type {any} */ input) => new Response("{}", String(input).includes("reflexer") ? { status: 503, headers: busy } : { status: 200 });
await bedrock.fetch(key, { fetch })("https://bedrock-runtime.us-east-1.amazonaws.com/model/m/invoke", { method: "POST", headers, body: replay })
  .catch((/** @type {any} */ failure) => thrown.push(failure.name));
console.log(JSON.stringify({ thrown }));

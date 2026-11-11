# reflexer with LiteLLM

Send LiteLLM's calls to OpenAI, Azure OpenAI, Anthropic, Gemini and Bedrock through reflexer: add one line. The line covers `litellm.completion` and `acompletion`, streamed or not, from your code or from a framework built on LiteLLM. LiteLLM sends its calls to other providers, or to another host (a router or a gateway given as `api_base`), as before. A [dry run](advanced.md#a-dry-run-give-reflexer-your-providers-answer) (`replay_response`) is the exception: the SDK sends it only to reflexer. The line does not cover LiteLLM's Proxy.

**Before you begin:** you need LiteLLM 1 on Python 3.10 or later, and the environment variable `REFLEXER_KEY` set to the reflexer key you got at onboarding. LiteLLM reads your provider keys where it read them before.

## 1. Install

The SDK is not on PyPI or npm yet. Install it from a clone of this repository ([README](../README.md#install)).

```sh
pip install --build-constraint reflexer-sdk/build-constraints.txt ./reflexer-sdk  # pip 26.1 or later
```
## 2. Add the line

Run the line once, before your first call. From then on, the SDK sends every call through reflexer, sync or async.

<!-- example: served python -->
```diff
  import os
  import litellm
+ import reflexer.litellm

+ reflexer.litellm.through(os.environ["REFLEXER_KEY"])
  reply = litellm.completion(model="openai/frontier-x", messages=[{"role": "user", "content": "Hi"}])
  print(reply.choices[0].message.content)
```

```text
Hello! How can I help you today?
```

The same line covers `anthropic/`, `azure/`, `gemini/` and `bedrock/` models, `acompletion` and `stream=True`. The line sets LiteLLM's `client_session`, `aclient_session` and `sync_transport`, and adds a callback. If you set any of these yourself, set them before the line, and append to `litellm.callbacks` instead of replacing it.

## 3. Verify

The reply looks the same whether reflexer or your provider answered. When reflexer answered, the reply's model name ends in `-reflexer`.

<!-- example: served -->
```python
import os
import litellm, reflexer.litellm

reflexer.litellm.through(os.environ["REFLEXER_KEY"])
reply = litellm.completion(model="openai/frontier-x", messages=[{"role": "user", "content": "Hi"}])
print(reply.model)
```

```text
frontier-x-reflexer
```

On Bedrock, the reply keeps your model's name. There, `reply._hidden_params["additional_headers"]["llm_provider-reflexer-answered-by"]` names who answered: `reflexer`, or `provider` when reflexer forwarded the call to Bedrock.

## Behavior

- **Reflexer down, slow or busy:** the SDK sends the call directly to your provider, and your code gets your provider's answer. The SDK logs a warning on the `reflexer` logger. After a failure, the SDK sends the next calls directly to your provider too, for about a minute at most. Then the SDK tries reflexer again.
- **Timeouts, Python:** your client's timeout applies to the call to reflexer. If that timeout expires, the SDK sends the call directly to your provider, with the same timeout. So one call can take up to two times your timeout. If reflexer had already forwarded the call, your provider may run the call twice and bill it twice.
- **Key refused:** if reflexer refuses your reflexer key, your provider SDK raises its authentication error, and the SDK does not send the call to your provider. If your reflexer key was revoked less than one day ago, the SDK still sends your calls directly to your provider, and logs a warning.
- **Which calls:** the SDK sends to reflexer only the calls that return a model's message. The SDK sends all other calls, and all calls to `http`, `localhost` or a private IP, to the address your code gave them, as before.
- **What leaves your machine:** the SDK sends the call to reflexer, with your provider key. When reflexer does not answer the call itself, reflexer uses this key to forward the call to your provider. Only reflexer receives your reflexer key.
- **Your whole process:** the line sets LiteLLM's own settings, so the SDK sends every LiteLLM call of your process through reflexer. If your code sets `client_session`, `aclient_session` or `sync_transport` after the line, or replaces the list with `litellm.callbacks = [...]`, the SDK no longer sees the calls that setting covers, and LiteLLM sends them directly to your provider: [Known limits](limits.md).
- **Gemini 3:** LiteLLM sends Gemini 3 calls to `v1alpha`, which reflexer does not take. The SDK sends those calls directly to Gemini.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. If you remove the line, your code works as before.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `sample=0.01` on `through`: the SDK sends that share of the calls to reflexer, and the other calls directly to your provider.
- `extra_headers={"Reflexer-Skip": "true"}` on a call: the SDK sends that call directly to your provider.
- `namespace=` on `through`: a [namespace](advanced.md#keep-calls-apart-a-namespace) for every call. To use another namespace on one call, add `extra_headers={"Reflexer-Namespace": "..."}` to that call.
- `answer=`, `store=`, `pass_through=` and `timeout_ms=` on `through`: [what reflexer does with your calls](advanced.md#tell-reflexer-what-to-do-with-your-calls).
- `base=` on `through`: reflexer's address, if reflexer gave you another one.

All options: [Advanced](advanced.md).

## Supported versions

LiteLLM 1 on Python 3.10 or later. With another major version of LiteLLM, `import reflexer.litellm` raises an error.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)

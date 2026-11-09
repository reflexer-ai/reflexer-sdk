# reflexer with LiteLLM

Reflexer in front of LiteLLM's calls to OpenAI, Azure OpenAI, Anthropic, Gemini and Bedrock: `litellm.completion` and `acompletion`, streamed or not, from your code or from a framework built on LiteLLM. Calls to its other providers, or to another host (a router or a gateway as `api_base`), go as before, but for a replay (`replay_response`), which goes to reflexer only. LiteLLM's Proxy is not covered.

**Before you begin:** LiteLLM 1 on Python 3.10+, and `REFLEXER_KEY` set to the key you got at onboarding. Your provider keys stay where LiteLLM reads them.

## 1. Install

Not on PyPI or npm yet: install from a clone of this repository ([README](../README.md#install)).

```sh
pip install ./reflexer-sdk
```
## 2. Add the line

Once, before your first call. Every call after it, sync or async, goes through reflexer.

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

The same line covers `anthropic/`, `azure/`, `gemini/` and `bedrock/` models, `acompletion` and `stream=True`. It sets LiteLLM's `client_session`, `aclient_session` and `sync_transport`, and adds a callback. Set yours before it, and append to `litellm.callbacks` rather than replace it.

## 3. Verify

The reply looks the same either way. A reply from reflexer has a model name ending in `-reflexer`.

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

On Bedrock the reply keeps your model's name: `reply._hidden_params["additional_headers"]["llm_provider-reflexer-answered-by"]` is `reflexer`.

## Behavior

- **Reflexer down, slow or busy:** the call goes to your provider, and your code gets your provider's answer. The SDK logs a warning on the `reflexer` logger. After a failure, the next calls go to your provider too, for about a minute at most, then reflexer is tried again.
- **Timeouts, Python:** your client's timeout covers the call to reflexer. If it fires, the call goes to your provider with the same timeout, so a call can take up to twice it. If reflexer had already forwarded the call, your provider may run it, and bill it, twice.
- **Key refused:** if reflexer refuses your reflexer key, your SDK raises its authentication error; the call does not go to your provider. A key revoked less than a day ago still sends calls to your provider, with a warning.
- **Which calls:** only the calls that return a model's message go to reflexer. Other calls, and calls to `http`, `localhost` or a private IP, go where they were sent, as before.
- **What leaves your machine:** the call, with your provider key, goes to reflexer, which uses the key to forward the call to your provider when it does not answer. The reflexer key goes to reflexer only.
- **Your whole process:** the line sets LiteLLM's own settings, so every LiteLLM call in the process goes through reflexer. A `client_session`, `aclient_session` or `sync_transport` you set after it, or a `litellm.callbacks = [...]` that replaces the list, sends the calls it covers to your provider directly: [Known limits](limits.md).
- **Gemini 3:** LiteLLM calls Gemini 3 models at `v1alpha`, which reflexer does not take: those calls go to Gemini directly.
- **What stays the same:** your arguments, the answer's types and fields, errors and streams. Remove the line and your code is as it was.

Every case, with what to do: [When reflexer fails](when-reflexer-fails.md). Every limit: [Known limits](limits.md).

## Options

- `sample=0.01` on `through`: send that share of the calls to reflexer, the rest to your provider.
- `extra_headers={"Reflexer-Pass-Through": "1"}` on a call: that call goes to your provider.
- `base=` on `through`: reflexer's address, if you were given another.

All of them: [Advanced](advanced.md).

## Supported versions

LiteLLM 1 on Python 3.10+. Another major of LiteLLM raises at `import reflexer.litellm`.

Next: [When reflexer fails](when-reflexer-fails.md) · [Advanced](advanced.md) · [Reference](reference.md)

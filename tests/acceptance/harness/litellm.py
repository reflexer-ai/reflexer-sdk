"""LiteLLM's library, on each provider whose wire reflexer takes but Bedrock's (its own: `bedrock.py`, `litellm`): one
call as a LiteLLM user writes it, by `litellm.completion` or `acompletion`, streamed or not. Reflexer's line is the
process's (`lines.litellm_line`)."""
import asyncio, time

from . import AZURE_ENDPOINT, AZURE_VERSION, MESSAGES, PROVIDER_KEY
from .bedrock import Outcome

CALLS = {  # each provider's call, with its own key; Gemini's model one LiteLLM calls at `v1beta` (Gemini 3's go to `v1alpha`)
    "litellm-openai": dict(model="openai/frontier-x", api_key=PROVIDER_KEY["openai"]),
    "litellm-azure": dict(model="azure/frontier-d", api_key=PROVIDER_KEY["azure"], api_base=AZURE_ENDPOINT, api_version=AZURE_VERSION),
    "litellm-anthropic": dict(model="anthropic/frontier-y", api_key=PROVIDER_KEY["anthropic"], max_tokens=8),
    "litellm-gemini": dict(model="gemini/gemini-2.5-flash", api_key=PROVIDER_KEY["gemini"]),
}
COLUMNS = tuple(CALLS)
KEY_HEADER = {"litellm-openai": "authorization", "litellm-azure": "api-key", "litellm-anthropic": "x-api-key", "litellm-gemini": "x-goog-api-key"}
UPSTREAM = {"litellm-azure": AZURE_ENDPOINT}  # the rest: the provider's own, named by none


def text_of(answer, stream):
    if stream:
        return "".join((chunk.choices[0].delta.content or "") for chunk in answer if chunk.choices)
    return answer.choices[0].message.content


def ask(t, is_async=False, stream=False, headers=None, settle=None):
    """One call on the case's provider: what the client saw, kept as the case's last. `settle()`: awaited in the call's own
    event loop after it, or called after a sync one (a callback LiteLLM runs once the call returned)."""
    import litellm
    given = dict(messages=MESSAGES, num_retries=0, timeout=10, stream=stream) | CALLS[t.sdk] | ({"extra_headers": headers} if headers else {})

    async def asked():
        answer = await litellm.acompletion(**given)
        said = text_of([chunk async for chunk in answer], True) if stream else text_of(answer, False)
        if settle:
            await settle()
        return said
    began = time.monotonic()
    try:
        if is_async:
            said = asyncio.run(asked())
        else:
            said = text_of(litellm.completion(**given), stream)
            if settle:
                asyncio.run(settle())
        t.last = Outcome(text=said, wall=time.monotonic() - began)
    except Exception as error:
        t.last = Outcome(error=error, wall=time.monotonic() - began)
    return t.last

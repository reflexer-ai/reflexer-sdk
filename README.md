# reflexer

Reflexer's SDK for Python. It sends a client's LLM calls through reflexer, on the provider SDK the client already uses; a call reflexer does not answer goes to the provider, as before.

    # client = openai.OpenAI(api_key=openai_key)
    client = reflexer.openai.OpenAI(api_key=openai_key, reflexer_key=reflexer_key)

No dependency of its own. Its security promises, and the check that holds each one: [SECURITY.md](SECURITY.md).

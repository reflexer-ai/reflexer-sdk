"""Each provider's wire: which of its calls go to reflexer, and where reflexer takes them (see `Reflexer`). Data only, no
SDK imported, so a line on a library that carries several providers' calls reads them all without their SDKs (LiteLLM's).
"""
CHAT = {  # openai's
    "reflexer_path": "/openai",
    "provider":      "https://api.openai.com",
    "calls":         r"/v1/(chat/completions|responses)$",
    "routers": {  # a router's own body keys are served on its own route; its other calls go as any base's
        "openrouter.ai":        {"reflexer_path": "/openrouter", "provider": "https://openrouter.ai", "calls": r"/api/v1/chat/completions$"},
        "ai-gateway.vercel.sh": {"reflexer_path": "/vercel", "provider": "https://ai-gateway.vercel.sh", "calls": r"/v1/chat/completions$"},
    },
}
AZURE = {  # each client's resource is its own host, always named as the upstream
    "reflexer_path": "/azure",
    "calls":         r"/openai/((deployments/[^/]+|v1)/(chat/completions|responses)|responses)$",  # the last, Azure's dated Responses
}
MESSAGES = {  # anthropic's
    "reflexer_path": "/anthropic",
    "provider":      "https://api.anthropic.com",
    "calls":         r"/v1/messages$",
}
GENERATE = {  # google-genai's
    "reflexer_path": "/gemini",
    "provider":      "https://generativelanguage.googleapis.com",
    "calls":         r"/v1(alpha|beta)?/models/[^/]+:(stream)?[gG]enerateContent$",
}

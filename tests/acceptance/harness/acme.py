"""A made-up provider's SDK, small and stock in shape: built on httpx, one call, an object made from each answer.
It stands for a provider this SDK does not know, to show what adding one takes (`lines.acme_http_client`)."""
import httpx

DEFAULT_BASE = "https://api.acme.example"


class Answer:
    def __init__(self, data, headers):
        self.text, self.usage, self.headers = data["text"], Usage(data.get("usage", {})), headers
        self.__dict__.update({k: v for k, v in data.items() if k not in ("text", "usage")})


class Usage:
    def __init__(self, data):
        self.__dict__.update(data)


class AcmeError(Exception):
    def __init__(self, status, text):
        super().__init__(f"{status}: {text}")
        self.status = status


class Acme:
    def __init__(self, api_key, base_url=DEFAULT_BASE, http_client=None, timeout=30.0):
        self.api_key, self.base_url, self.timeout = api_key, base_url.rstrip("/"), timeout
        self.http = http_client or httpx.Client(follow_redirects=True)

    def ask(self, model, prompt, extra_headers=None, timeout=None):
        headers = {"x-acme-key": self.api_key} | (extra_headers or {})
        response = self.http.post(f"{self.base_url}/v2/ask", json={"model": model, "prompt": prompt}, headers=headers,
                                  timeout=self.timeout if timeout is None else timeout)
        if response.status_code >= 400:
            raise AcmeError(response.status_code, response.text)
        return Answer(response.json(), response.headers)

"""Client for the model gateway (an OpenAI-compatible endpoint). Tools use an alias, never a provider model name."""
import httpx


class Gateway:
    def __init__(self, url: str, alias: str, api_key: str = "", timeout_s: float = 30.0,
                 client: httpx.Client | None = None):
        self.url, self.alias, self.api_key, self.timeout_s = url.rstrip("/"), alias, api_key, timeout_s
        self.client = client or httpx.Client()

    def complete(self, system: str, user: str) -> str:
        r = self.client.post(
            f"{self.url}/v1/chat/completions",
            json={"model": self.alias, "temperature": 0, "max_tokens": 400,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

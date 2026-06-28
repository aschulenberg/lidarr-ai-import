from __future__ import annotations

import requests

from .base import AIProvider

_DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider(AIProvider):
    def _complete(self, prompt: str) -> str:
        url = f"{(self.base_url or _DEFAULT_BASE_URL).rstrip('/')}/api/chat"
        resp = requests.post(
            url,
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
            },
            timeout=120,
        )
        if not resp.ok:
            raise RuntimeError(f"Ollama API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        return data.get("message", {}).get("content", "")

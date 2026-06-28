from __future__ import annotations

import requests

from .base import AIProvider

_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(AIProvider):
    def _complete(self, prompt: str) -> str:
        url = f"{(self.base_url or _DEFAULT_BASE_URL).rstrip('/')}/messages"
        resp = requests.post(
            url,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        if not resp.ok:
            raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        return "".join(block.get("text", "") for block in data.get("content", []))

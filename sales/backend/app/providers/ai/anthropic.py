"""Anthropic Messages API. Docs: https://platform.claude.com/docs/en/models/overview"""
import httpx

from app.providers.ai.base import AIProvider
from app.providers.base import BadResponse

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(AIProvider):
    name = "anthropic"
    display_name = "Anthropic Claude"
    # Fastest/cheapest current model, suited to classification and extraction.
    default_model = "claude-haiku-5-5"
    base_url = "https://api.anthropic.com"
    docs_url = "https://platform.claude.com/docs/en/models/overview"

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}

    async def _complete(self, system: str, prompt: str, max_tokens: int) -> tuple[str, dict]:
        body = {"model": self.model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": prompt}]}
        resp = await self._send("POST", "/v1/messages", json=body, headers=self._headers())
        data = resp.json()
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise BadResponse("Anthropic response had no content", http_status=resp.status_code)
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise BadResponse(f"Anthropic returned no text (stop_reason={data.get('stop_reason')})",
                              http_status=resp.status_code)
        usage = data.get("usage") or {}
        return text, {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}

    async def _ping(self) -> httpx.Response:
        return await self._send("GET", f"/v1/models/{self.model}", headers=self._headers())

"""OpenAI Responses API. Docs: https://developers.openai.com/api/docs/models"""
import httpx

from app.providers.ai.base import AIProvider
from app.providers.base import BadResponse


class OpenAIProvider(AIProvider):
    name = "openai"
    display_name = "OpenAI"
    # Cheapest current text model as of 2026-10.
    default_model = "gpt-6-luna"
    base_url = "https://api.openai.com"
    docs_url = "https://developers.openai.com/api/docs/models"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def _complete(self, system: str, prompt: str, max_tokens: int) -> tuple[str, dict]:
        # JSON mode (schema is in the instructions and validated locally): strict
        # json_schema rejects ordinary Pydantic schemas (optional fields, $defs).
        body = {"model": self.model, "instructions": system, "input": prompt,
                "max_output_tokens": max_tokens, "text": {"format": {"type": "json_object"}}}
        resp = await self._send("POST", "/v1/responses", json=body, headers=self._headers())
        data = resp.json()
        texts, refusal = [], None
        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
                elif part.get("type") == "refusal":
                    refusal = part.get("refusal")
        if not texts:
            reason = refusal or (data.get("incomplete_details") or {}).get("reason") or data.get("status")
            raise BadResponse(f"OpenAI returned no text ({reason})", http_status=resp.status_code)
        usage = data.get("usage") or {}
        return "".join(texts), {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}

    async def _ping(self) -> httpx.Response:
        return await self._send("GET", f"/v1/models/{self.model}", headers=self._headers())

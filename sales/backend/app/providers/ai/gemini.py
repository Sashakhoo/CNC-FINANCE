"""Google Gemini via REST generateContent (v1beta). Key goes in the
x-goog-api-key header, never the URL. Docs: https://ai.google.dev/api/generate-content"""
import httpx

from app.providers.ai.base import AIProvider
from app.providers.base import BadResponse


class GeminiProvider(AIProvider):
    name = "gemini"
    display_name = "Google Gemini"
    # Stable Flash-Lite tier as of 2026-10 (gemini-2.0-* are shut down).
    default_model = "gemini-3.5-flash-lite"
    base_url = "https://generativelanguage.googleapis.com"
    docs_url = "https://ai.google.dev/gemini-api/docs/models"

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    async def _complete(self, system: str, prompt: str, max_tokens: int) -> tuple[str, dict]:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens,
                                 "temperature": 0.2},
        }
        resp = await self._send("POST", f"/v1beta/models/{self.model}:generateContent", json=body,
                                headers=self._headers())
        data = resp.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except (KeyError, IndexError, TypeError) as e:
            reason = (data.get("promptFeedback") or {}).get("blockReason") or "no candidates"
            raise BadResponse(f"Gemini returned no text ({reason})", http_status=resp.status_code) from e
        usage = data.get("usageMetadata") or {}
        return text, {"input_tokens": usage.get("promptTokenCount"), "output_tokens": usage.get("candidatesTokenCount")}

    async def _ping(self) -> httpx.Response:
        return await self._send("GET", f"/v1beta/models/{self.model}", headers=self._headers())

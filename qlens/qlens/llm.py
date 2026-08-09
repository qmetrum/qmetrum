from __future__ import annotations

from typing import Optional

from .config import DEFAULT_MODEL, get_api_key


class GeminiLLM:
    """Thin Gemini wrapper on the google-genai SDK (the same one the Qmetrum
    backend uses, see services/forecasting_service_py/app/agents/llm.py). Lazy-
    imports the SDK so the package imports and tests run without it or a key."""

    def __init__(self, model: Optional[str] = None):
        self.model_name = model or DEFAULT_MODEL
        self._client = None

    def _ensure(self) -> None:
        if self._client is not None:
            return
        key = get_api_key()
        if not key:
            raise RuntimeError("GOOGLE_API_KEY (or GEMINI_API_KEY) is not set.")
        from google import genai  # lazy

        self._client = genai.Client(api_key=key)

    def generate(self, prompt: str) -> str:
        self._ensure()
        resp = self._client.models.generate_content(
            model=self.model_name, contents=prompt
        )
        return (getattr(resp, "text", "") or "").strip()

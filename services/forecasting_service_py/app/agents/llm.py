"""Thin LLM wrapper. One function: `generate()`.

- Default provider: Google Gemini 2.5 Flash.
- Content-hash caching via the `agentrun` table.
- Logs every call (prompt tokens, output tokens, latency, status).

Callers include anything in the input that should invalidate the cache — e.g.,
portfolio snapshot hashes, news item ids — inside `cache_key_extra`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from dotenv import load_dotenv
from sqlmodel import Session, select

from app.db.database import engine
from app.db.models import AgentRun


# Load a .env file from the working directory (or any parent) the first time
# this module is imported. Idempotent — safe if other modules also call it.
load_dotenv()

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"


@dataclass
class LlmResult:
    text: str
    model: str
    prompt_tokens: int
    output_tokens: int
    latency_ms: int
    cached: bool
    input_hash: str


def _hash_input(agent_name: str, model: str, prompt: str, extra: dict[str, Any]) -> str:
    payload = {
        "agent": agent_name,
        "model": model,
        "prompt": prompt,
        "extra": extra,
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _find_cached(session: Session, agent_name: str, model: str, input_hash: str) -> Optional[AgentRun]:
    return session.exec(
        select(AgentRun)
        .where(AgentRun.agent_name == agent_name)
        .where(AgentRun.model == model)
        .where(AgentRun.input_hash == input_hash)
        .where(AgentRun.status == "ok")
        .order_by(AgentRun.created_at.desc())
    ).first()


def _persist(
    session: Session,
    agent_name: str,
    model: str,
    input_hash: str,
    output: str,
    prompt_tokens: int,
    output_tokens: int,
    latency_ms: int,
    status: str,
    error: Optional[str],
    extra: dict[str, Any],
) -> None:
    run = AgentRun(
        agent_name=agent_name,
        model=model,
        input_hash=input_hash,
        output=output,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        status=status,
        error=error,
        extra=extra,
    )
    session.add(run)
    session.commit()


def _call_gemini(prompt: str, model: str, schema: Optional[Any]) -> tuple[str, int, int]:
    """Returns (text, prompt_tokens, output_tokens). Raises on error."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise RuntimeError(
            "google-genai is not installed. Add `google-genai` to requirements.txt."
        ) from e

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY (or GEMINI_API_KEY) is not set")

    client = genai.Client(api_key=api_key)

    config_kwargs: dict[str, Any] = {}
    if schema is not None:
        config_kwargs["response_mime_type"] = "application/json"
        config_kwargs["response_schema"] = schema

    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs) if config_kwargs else None,
    )

    text = (response.text or "").strip()
    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    return text, prompt_tokens, output_tokens


def generate(
    prompt: str,
    *,
    agent_name: str,
    model: Optional[str] = None,
    schema: Optional[Any] = None,
    cache_key_extra: Optional[dict[str, Any]] = None,
    use_cache: bool = True,
) -> LlmResult:
    """Call the LLM and log the run.

    Args:
        prompt: full text prompt for the model.
        agent_name: short label (e.g. "portfolio_commentary") — used for cache
            namespacing and observability filtering.
        model: override model id; defaults to DEFAULT_MODEL.
        schema: Pydantic BaseModel subclass or JSON Schema dict for structured
            output. If set, Gemini is asked to return JSON conforming to the
            schema; `result.text` will be a JSON string the caller parses.
        cache_key_extra: any additional facts that should invalidate the cache
            (e.g. `{"snapshot_hash": "..."}`). Defaults to {}.
        use_cache: when False, bypasses the cache lookup.

    Returns an LlmResult. On failure, persists an error row and re-raises.
    """
    model = model or DEFAULT_MODEL
    extra = dict(cache_key_extra or {})
    input_hash = _hash_input(agent_name, model, prompt, extra)

    with Session(engine) as session:
        if use_cache:
            cached = _find_cached(session, agent_name, model, input_hash)
            if cached is not None:
                return LlmResult(
                    text=cached.output,
                    model=cached.model,
                    prompt_tokens=cached.prompt_tokens,
                    output_tokens=cached.output_tokens,
                    latency_ms=cached.latency_ms,
                    cached=True,
                    input_hash=input_hash,
                )

        start = time.perf_counter()
        try:
            text, ptok, otok = _call_gemini(prompt, model, schema)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            log.exception("LLM call failed (agent=%s, model=%s)", agent_name, model)
            _persist(
                session,
                agent_name=agent_name,
                model=model,
                input_hash=input_hash,
                output="",
                prompt_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                status="error",
                error=str(exc)[:2000],
                extra=extra,
            )
            raise

        latency_ms = int((time.perf_counter() - start) * 1000)
        _persist(
            session,
            agent_name=agent_name,
            model=model,
            input_hash=input_hash,
            output=text,
            prompt_tokens=ptok,
            output_tokens=otok,
            latency_ms=latency_ms,
            status="ok",
            error=None,
            extra=extra,
        )

        return LlmResult(
            text=text,
            model=model,
            prompt_tokens=ptok,
            output_tokens=otok,
            latency_ms=latency_ms,
            cached=False,
            input_hash=input_hash,
        )

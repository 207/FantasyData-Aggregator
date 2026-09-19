from __future__ import annotations

"""LLM backends: Google Gemini (default), optional OpenAI / Anthropic via user API keys.

Ollama has been removed as a default path. Set LLM_PROVIDER=ollama only if you
intentionally keep a gated local path; Gemini free tier is the supported default.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
load_dotenv(CONFIG_DIR / ".env")

log = logging.getLogger(__name__)

SCHEMA_KEYS = ("trades", "waivers", "start_sit")

# Best free-tier Flash model (Google: "most intelligent Flash"; 2.5 blocked for new keys).
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

# High-demand / rate-limit retries: wait base, then 2x, 4x, … before each next try.
DEFAULT_RETRY_MAX = 6
DEFAULT_RETRY_BASE_SECONDS = 2.0


def _retry_settings() -> tuple[int, float]:
    try:
        max_attempts = max(1, int(os.getenv("LLM_RETRY_MAX", str(DEFAULT_RETRY_MAX)) or DEFAULT_RETRY_MAX))
    except ValueError:
        max_attempts = DEFAULT_RETRY_MAX
    try:
        base = float(os.getenv("LLM_RETRY_BASE_SECONDS", str(DEFAULT_RETRY_BASE_SECONDS)) or DEFAULT_RETRY_BASE_SECONDS)
        base = max(0.5, base)
    except ValueError:
        base = DEFAULT_RETRY_BASE_SECONDS
    return max_attempts, base


def _error_status_code(exc: BaseException) -> int | None:
    for attr in ("code", "status_code", "status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
    resp = getattr(exc, "response", None)
    if resp is not None:
        code = getattr(resp, "status_code", None)
        if isinstance(code, int):
            return code
    return None


def _is_retryable_llm_error(exc: BaseException) -> bool:
    """True for transient overload / rate-limit failures worth backing off."""
    code = _error_status_code(exc)
    if code in {408, 429, 500, 502, 503, 504}:
        return True
    msg = str(exc).lower()
    needles = (
        "high demand",
        "try again",
        "unavailable",
        "resource_exhausted",
        "resource exhausted",
        "rate limit",
        "quota exceeded",
        "temporarily",
        "overloaded",
        "503",
        "429",
    )
    return any(n in msg for n in needles)


def _call_with_backoff(fn: Callable[[], str], *, label: str) -> str:
    """Run fn; on retryable errors sleep base, 2x, 4x, … then retry until max attempts."""
    max_attempts, base = _retry_settings()
    last: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt >= max_attempts or not _is_retryable_llm_error(exc):
                raise
            wait = base * (2 ** (attempt - 1))
            log.warning(
                "%s attempt %s/%s failed (%s); waiting %.1fs then retrying",
                label,
                attempt,
                max_attempts,
                exc,
                wait,
            )
            time.sleep(wait)
    assert last is not None
    raise last


def retry_settings() -> tuple[int, float]:
    """Public: (max_attempts, base_seconds) for UI captions / callers."""
    return _retry_settings()


def _gemini_api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()


def llm_config() -> dict[str, str]:
    return {
        "provider": (os.getenv("LLM_PROVIDER", "gemini") or "gemini").strip().lower(),
        "gemini_api_key": _gemini_api_key(),
        "gemini_model": (os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL).strip(),
        "context_format": (os.getenv("LLM_CONTEXT_FORMAT", "toon") or "toon").strip().lower(),
        "openai_api_key": (os.getenv("OPENAI_API_KEY") or "").strip(),
        "openai_model": (os.getenv("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip(),
        "anthropic_api_key": (os.getenv("ANTHROPIC_API_KEY") or "").strip(),
        "anthropic_model": (os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest") or "").strip(),
        # Gated legacy — not documented as the default path.
        "ollama_base_url": (os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/"),
        "ollama_model": (os.getenv("OLLAMA_MODEL", "llama3.1:8b") or "llama3.1:8b").strip(),
        "ollama_num_ctx": (os.getenv("OLLAMA_NUM_CTX", "16384") or "16384").strip(),
        "ollama_num_predict": (os.getenv("OLLAMA_NUM_PREDICT", "2048") or "2048").strip(),
    }


def describe_setup() -> str:
    cfg = llm_config()
    provider = cfg["provider"]
    if provider == "openai":
        return (
            "LLM_PROVIDER=openai — set OPENAI_API_KEY in config/.env "
            f"(model: {cfg['openai_model']})."
        )
    if provider == "anthropic":
        return (
            "LLM_PROVIDER=anthropic — set ANTHROPIC_API_KEY in config/.env "
            f"(model: {cfg['anthropic_model']})."
        )
    if provider == "ollama":
        return (
            f"LLM_PROVIDER=ollama (legacy/gated) at {cfg['ollama_base_url']} "
            f"model `{cfg['ollama_model']}`. Prefer Gemini: set LLM_PROVIDER=gemini "
            "and GEMINI_API_KEY from https://aistudio.google.com/apikey"
        )
    key = cfg["gemini_api_key"]
    if not key:
        return (
            "Google Gemini is the default LLM. Set GEMINI_API_KEY (or GOOGLE_API_KEY) "
            "in config/.env — get a free key at https://aistudio.google.com/apikey "
            f"(model: {cfg['gemini_model']}). Optional: GEMINI_MODEL=gemini-3.5-flash-lite "
            "for higher free-tier request volume."
        )
    return (
        f"Gemini model `{cfg['gemini_model']}` "
        f"(context={cfg.get('context_format') or 'toon'}). "
        "Key loaded from GEMINI_API_KEY / GOOGLE_API_KEY."
    )


def _gemini_chat(system: str, user: str, cfg: dict[str, str]) -> str:
    if not cfg["gemini_api_key"]:
        raise RuntimeError(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set in config/.env. "
            "Get a free key at https://aistudio.google.com/apikey — "
            "Google AI Studio → Get API key → Create API key, then paste into config/.env."
        )
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "google-genai package is not installed. Run: pip install google-genai"
        ) from exc

    client = genai.Client(api_key=cfg["gemini_api_key"])
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0.3,
        max_output_tokens=4096,
        response_mime_type="application/json",
    )

    def _once() -> str:
        response = client.models.generate_content(
            model=cfg["gemini_model"],
            contents=user,
            config=config,
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini returned empty content")
        return text

    return _call_with_backoff(_once, label=f"Gemini:{cfg['gemini_model']}")


def _ollama_chat(system: str, user: str, cfg: dict[str, str]) -> str:
    """Legacy gated path — only used when LLM_PROVIDER=ollama."""
    url = f"{cfg['ollama_base_url']}/api/chat"
    try:
        num_ctx = max(2048, int(cfg.get("ollama_num_ctx") or 16384))
    except ValueError:
        num_ctx = 16384
    try:
        num_predict = max(256, int(cfg.get("ollama_num_predict") or 2048))
    except ValueError:
        num_predict = 2048
    payload = {
        "model": cfg["ollama_model"],
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {
            "temperature": 0.2,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }
    with httpx.Client(timeout=300.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    msg = (data.get("message") or {}).get("content") or ""
    if not msg:
        raise RuntimeError("Ollama returned empty content")
    return msg


def _openai_chat(system: str, user: str, cfg: dict[str, str]) -> str:
    if not cfg["openai_api_key"]:
        raise RuntimeError("OPENAI_API_KEY is not set in config/.env")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['openai_api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg["openai_model"],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def _anthropic_chat(system: str, user: str, cfg: dict[str, str]) -> str:
    if not cfg["anthropic_api_key"]:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in config/.env")
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": cfg["anthropic_api_key"],
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": cfg["anthropic_model"],
        "max_tokens": 4096,
        "temperature": 0.3,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    parts = data.get("content") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text:
        raise RuntimeError("Anthropic returned empty content")
    return text


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(cleaned[start : end + 1])
        else:
            raise RuntimeError(f"LLM did not return valid JSON. Preview: {cleaned[:400]}") from None
    if not isinstance(data, dict):
        raise RuntimeError("LLM JSON root must be an object")
    return data


def _looks_like_recs(data: dict[str, Any]) -> bool:
    """Reject hallucinated JSON that ignores our schema."""
    has_list = any(isinstance(data.get(k), list) for k in SCHEMA_KEYS)
    if has_list:
        return True
    return all(k in data for k in ("trades", "waivers")) and isinstance(data.get("notes"), str)


def complete_json(system: str, user: str) -> tuple[dict[str, Any], str]:
    """
    Call the configured LLM and parse a JSON object response.

    Returns (parsed_dict, raw_text).
    Raises RuntimeError with a user-facing message on setup/network/parse failures.
    """
    cfg = llm_config()
    provider = cfg["provider"]
    raw = ""
    try:
        def _dispatch() -> str:
            if provider == "openai":
                return _openai_chat(system, user, cfg)
            if provider == "anthropic":
                return _anthropic_chat(system, user, cfg)
            if provider == "ollama":
                return _ollama_chat(system, user, cfg)
            return _gemini_chat(system, user, cfg)

        # Gemini already retries inside _gemini_chat; wrap others the same way.
        if provider == "gemini" or provider not in {"openai", "anthropic", "ollama"}:
            raw = _dispatch()
        else:
            raw = _call_with_backoff(_dispatch, label=f"LLM:{provider}")
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Cannot reach LLM ({provider}). {describe_setup()} Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        body = (exc.response.text or "")[:300]
        log.error("LLM HTTP %s (%s): %s", exc.response.status_code, provider, body)
        raise RuntimeError(
            f"LLM HTTP error ({provider}): {exc.response.status_code}. "
            f"See logs for details. {describe_setup()}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"LLM call failed ({provider}): {exc}") from exc

    try:
        data = _parse_json_object(raw)
    except RuntimeError:
        log.error("LLM JSON parse failure. Raw output (%s chars): %s", len(raw), raw[:2000])
        raise

    if not _looks_like_recs(data):
        log.error(
            "LLM returned JSON without recs schema. keys=%s raw=%s",
            list(data.keys()),
            raw[:2000],
        )
        raise RuntimeError(
            "LLM returned JSON that is not trade/waiver recommendations "
            f"(keys={list(data.keys())}). Raw preview: {raw[:400]}"
        )
    return data, raw

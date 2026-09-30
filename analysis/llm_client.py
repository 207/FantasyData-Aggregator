from __future__ import annotations

"""LLM backends: OpenAI (when keyed), Google Gemini fallback, optional Anthropic.

Set LLM_PROVIDER=openai with OPENAI_API_KEY for the preferred path.
LLM_PROVIDER=gemini (default if unset) keeps the free-tier Gemini fallback.
Ollama remains a gated legacy path only when LLM_PROVIDER=ollama.
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import httpx
from dotenv import load_dotenv

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
load_dotenv(CONFIG_DIR / ".env")

log = logging.getLogger(__name__)

SCHEMA_KEYS = ("trades", "waivers", "start_sit")

# Parse-failure re-ask attempts (after the first generate).
DEFAULT_JSON_PARSE_RETRIES = 2


class LLMParseError(RuntimeError):
    """JSON parse / schema failure that still carries the raw model text."""

    def __init__(self, message: str, *, raw: str = ""):
        super().__init__(message)
        self.raw = raw

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
        "openai_model": (os.getenv("OPENAI_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini").strip(),
        "anthropic_api_key": (os.getenv("ANTHROPIC_API_KEY") or "").strip(),
        "anthropic_model": (os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest") or "").strip(),
        # Gated legacy — not documented as the default path.
        "ollama_base_url": (os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/"),
        "ollama_model": (os.getenv("OLLAMA_MODEL", "llama3.1:8b") or "llama3.1:8b").strip(),
        "ollama_num_ctx": (os.getenv("OLLAMA_NUM_CTX", "16384") or "16384").strip(),
        "ollama_num_predict": (os.getenv("OLLAMA_NUM_PREDICT", "2048") or "2048").strip(),
    }


def active_provider_model() -> tuple[str, str]:
    """Return (display name, model id) for the currently configured LLM."""
    cfg = llm_config()
    provider = cfg["provider"]
    if provider == "openai":
        return "OpenAI", cfg["openai_model"]
    if provider == "anthropic":
        return "Anthropic", cfg["anthropic_model"]
    if provider == "ollama":
        return "Ollama", cfg["ollama_model"]
    return "Gemini", cfg["gemini_model"]


def generate_action_label() -> str:
    """UI heading for generate, e.g. 'Generate with OpenAI · gpt-5.6-terra'."""
    name, model = active_provider_model()
    return f"Generate with {name} · {model}"


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


def _openai_omits_temperature(model: str) -> bool:
    """GPT-5 reasoning / o-series reject non-default temperature."""
    m = (model or "").strip().lower()
    if m.startswith("gpt-5-chat"):
        return False
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _openai_chat(system: str, user: str, cfg: dict[str, str]) -> str:
    if not cfg["openai_api_key"]:
        raise RuntimeError("OPENAI_API_KEY is not set in config/.env")
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg['openai_api_key']}",
        "Content-Type": "application/json",
    }
    model = cfg["openai_model"]
    payload: dict[str, Any] = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    # Reasoning GPT-5 / o-series only allow the default temperature (1).
    if not _openai_omits_temperature(model):
        payload["temperature"] = 0.3
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


def _json_parse_retries() -> int:
    try:
        return max(0, int(os.getenv("LLM_JSON_PARSE_RETRIES", str(DEFAULT_JSON_PARSE_RETRIES))))
    except ValueError:
        return DEFAULT_JSON_PARSE_RETRIES


def _strip_markdown_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned.startswith("```"):
        return cleaned
    # Drop opening fence (``` or ```json)
    first_nl = cleaned.find("\n")
    if first_nl >= 0:
        cleaned = cleaned[first_nl + 1 :]
    else:
        cleaned = cleaned.lstrip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()
    if cleaned.rstrip().endswith("```"):
        cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip()


def _extract_json_object(text: str) -> str | None:
    """Slice outermost `{...}` only when surrounding prose is present."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    before = text[:start].strip()
    after = text[end + 1 :].strip().strip("`").strip()
    # Surrounding prose with a closed object — safe to slice.
    if before or after:
        return text[start : end + 1]
    return None


def _repair_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] (common Gemini glitch)."""
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _close_truncated_json(text: str) -> str | None:
    """
    Best-effort close for truncated objects/arrays.
    Skips repair when an open string looks unterminated.
    """
    in_string = False
    escape = False
    stack: list[str] = []
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack[-1] != ch:
                return None
            stack.pop()
    if in_string or not stack:
        return None
    trimmed = text.rstrip()
    for sep in (",", ":"):
        if trimmed.endswith(sep):
            trimmed = trimmed[:-1].rstrip()
            break
    return trimmed + "".join(reversed(stack))


def _candidate_json_strings(text: str) -> list[str]:
    """Ordered unique candidates to try with json.loads."""
    cleaned = _strip_markdown_fences(text)
    repaired_full = _repair_trailing_commas(cleaned)
    closed_full = _close_truncated_json(repaired_full) or _close_truncated_json(cleaned)
    extracted = _extract_json_object(cleaned)
    repaired_ext = _repair_trailing_commas(extracted) if extracted else None
    closed_ext = None
    if extracted:
        closed_ext = _close_truncated_json(repaired_ext or extracted)
    out: list[str] = []
    for cand in (
        cleaned,
        repaired_full,
        closed_full,
        extracted,
        repaired_ext,
        closed_ext,
    ):
        if cand and cand not in out:
            out.append(cand)
    return out


def _parse_json_object(text: str) -> dict[str, Any]:
    """
    Parse a JSON object from model text.

    Strips markdown fences, extracts the outermost object, repairs common
    Gemini glitches (trailing commas, mild truncation). Never raises
    json.JSONDecodeError — always LLMParseError / RuntimeError.
    """
    last_err: json.JSONDecodeError | None = None
    for candidate in _candidate_json_strings(text):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_err = exc
            continue
        if not isinstance(data, dict):
            raise LLMParseError(
                "LLM JSON root must be an object",
                raw=text,
            )
        return data

    preview = (text or "")[:400]
    detail = f"{last_err}" if last_err else "no JSON object found"
    raise LLMParseError(
        f"LLM did not return valid JSON ({detail}). Preview: {preview}",
        raw=text or "",
    )


def _looks_like_recs(data: dict[str, Any]) -> bool:
    """Reject hallucinated JSON that ignores our schema."""
    has_list = any(isinstance(data.get(k), list) for k in SCHEMA_KEYS)
    if has_list:
        return True
    return all(k in data for k in ("trades", "waivers")) and isinstance(data.get("notes"), str)


def _dispatch_chat(system: str, user: str, cfg: dict[str, str]) -> str:
    provider = cfg["provider"]

    def _once() -> str:
        if provider == "openai":
            return _openai_chat(system, user, cfg)
        if provider == "anthropic":
            return _anthropic_chat(system, user, cfg)
        if provider == "ollama":
            return _ollama_chat(system, user, cfg)
        return _gemini_chat(system, user, cfg)

    # Gemini already retries inside _gemini_chat; wrap others the same way.
    if provider == "gemini" or provider not in {"openai", "anthropic", "ollama"}:
        return _once()
    return _call_with_backoff(_once, label=f"LLM:{provider}")


def _repair_user_prompt(bad_raw: str, parse_error: str) -> str:
    return (
        "Your previous reply was not valid JSON and could not be parsed.\n"
        f"Parser error: {parse_error}\n\n"
        "Reply again with ONLY a single valid JSON object (no markdown fences, "
        "no commentary). Required keys: trades (array), waivers (array), "
        "start_sit (array), notes (string). Fix any trailing commas, missing "
        "commas, or truncated braces.\n\n"
        "Invalid previous output (for reference — do not repeat the mistake):\n"
        f"{(bad_raw or '')[:3500]}"
    )


def complete_json(system: str, user: str) -> tuple[dict[str, Any], str]:
    """
    Call the configured LLM and parse a JSON object response.

    Returns (parsed_dict, raw_text).
    Raises RuntimeError / LLMParseError with a user-facing message on failure.
    On parse failure, re-asks the model up to LLM_JSON_PARSE_RETRIES times
    for valid JSON only. LLMParseError.raw always carries the last raw text.
    """
    cfg = llm_config()
    provider = cfg["provider"]
    raw = ""
    parse_retries = _json_parse_retries()
    prompt_user = user
    last_parse_exc: BaseException | None = None

    for attempt in range(parse_retries + 1):
        try:
            raw = _dispatch_chat(system, prompt_user, cfg)
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot reach LLM ({provider}). {describe_setup()} Detail: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = (exc.response.text or "")[:300]
            log.error("LLM HTTP %s (%s): %s", exc.response.status_code, provider, body)
            detail = body
            try:
                err = exc.response.json().get("error") or {}
                if isinstance(err, dict) and err.get("message"):
                    detail = str(err["message"])
            except Exception:  # noqa: BLE001 — fall back to raw body
                pass
            raise RuntimeError(
                f"LLM HTTP error ({provider}): {exc.response.status_code} — {detail} "
                f"{describe_setup()}"
            ) from exc
        except LLMParseError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"LLM call failed ({provider}): {exc}") from exc

        try:
            data = _parse_json_object(raw)
        except (LLMParseError, json.JSONDecodeError, ValueError) as exc:
            last_parse_exc = exc
            log.error(
                "LLM JSON parse failure (attempt %s/%s). Raw (%s chars): %s",
                attempt + 1,
                parse_retries + 1,
                len(raw),
                raw[:2000],
            )
            if attempt >= parse_retries:
                break
            prompt_user = _repair_user_prompt(raw, str(exc))
            continue

        if not _looks_like_recs(data):
            msg = (
                "LLM returned JSON that is not trade/waiver recommendations "
                f"(keys={list(data.keys())}). Raw preview: {raw[:400]}"
            )
            log.error(
                "LLM returned JSON without recs schema. keys=%s raw=%s",
                list(data.keys()),
                raw[:2000],
            )
            last_parse_exc = LLMParseError(msg, raw=raw)
            if attempt >= parse_retries:
                raise last_parse_exc
            prompt_user = _repair_user_prompt(raw, msg)
            continue

        return data, raw

    err_msg = str(last_parse_exc) if last_parse_exc else "LLM did not return valid JSON"
    raise LLMParseError(err_msg, raw=raw)

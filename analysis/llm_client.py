from __future__ import annotations

"""LLM backends: Ollama (default), optional OpenAI / Anthropic via user API keys."""

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
load_dotenv(CONFIG_DIR / ".env")

log = logging.getLogger(__name__)

SCHEMA_KEYS = ("trades", "waivers", "start_sit")


def llm_config() -> dict[str, str]:
    return {
        "provider": (os.getenv("LLM_PROVIDER", "ollama") or "ollama").strip().lower(),
        "ollama_base_url": (os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/"),
        "ollama_model": (os.getenv("OLLAMA_MODEL", "llama3.1:8b") or "llama3.1:8b").strip(),
        # Default Ollama num_ctx is ~2048 — far too small for league JSON. Raise it.
        "ollama_num_ctx": (os.getenv("OLLAMA_NUM_CTX", "16384") or "16384").strip(),
        "ollama_num_predict": (os.getenv("OLLAMA_NUM_PREDICT", "2048") or "2048").strip(),
        # TOON packs more detail into fewer tokens than compact JSON (default).
        "context_format": (os.getenv("LLM_CONTEXT_FORMAT", "toon") or "toon").strip().lower(),
        "openai_api_key": (os.getenv("OPENAI_API_KEY") or "").strip(),
        "openai_model": (os.getenv("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip(),
        "anthropic_api_key": (os.getenv("ANTHROPIC_API_KEY") or "").strip(),
        "anthropic_model": (os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest") or "").strip(),
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
    fmt = cfg.get("context_format") or "toon"
    return (
        f"Default Ollama at {cfg['ollama_base_url']} model `{cfg['ollama_model']}` "
        f"(num_ctx={cfg['ollama_num_ctx']}, num_predict={cfg['ollama_num_predict']}, "
        f"context={fmt}). "
        "Install: https://ollama.com — then `ollama pull llama3.1:8b` "
        "(or another 7B–14B for ~24GB Mac). Optional remote: point OLLAMA_BASE_URL "
        "at a Windows RTX 3070 host later."
    )


def _ollama_chat(system: str, user: str, cfg: dict[str, str]) -> str:
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
    prompt_eval = data.get("prompt_eval_count")
    if prompt_eval is not None and prompt_eval >= num_ctx - 64:
        log.warning(
            "Ollama prompt_eval_count=%s near num_ctx=%s — context may still be truncated",
            prompt_eval,
            num_ctx,
        )
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
    """Reject hallucinated JSON that ignores our schema (common when context is truncated)."""
    has_list = any(isinstance(data.get(k), list) for k in SCHEMA_KEYS)
    if has_list:
        return True
    # Accept empty-but-valid schema with notes only
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
        if provider == "openai":
            raw = _openai_chat(system, user, cfg)
        elif provider == "anthropic":
            raw = _anthropic_chat(system, user, cfg)
        else:
            raw = _ollama_chat(system, user, cfg)
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Cannot reach LLM ({provider}). {describe_setup()} Detail: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"LLM HTTP error ({provider}): {exc.response.status_code} {exc.response.text[:300]}"
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
            f"(keys={list(data.keys())}). Often caused by a too-small Ollama num_ctx. "
            f"Raw preview: {raw[:400]}"
        )
    return data, raw

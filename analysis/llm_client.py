from __future__ import annotations

"""LLM backends: Ollama (default), optional OpenAI / Anthropic via user API keys."""

import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
load_dotenv(CONFIG_DIR / ".env")


def llm_config() -> dict[str, str]:
    return {
        "provider": (os.getenv("LLM_PROVIDER", "ollama") or "ollama").strip().lower(),
        "ollama_base_url": (os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/"),
        "ollama_model": (os.getenv("OLLAMA_MODEL", "llama3.1:8b") or "llama3.1:8b").strip(),
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
    return (
        f"Default Ollama at {cfg['ollama_base_url']} model `{cfg['ollama_model']}`. "
        "Install: https://ollama.com — then `ollama pull llama3.1:8b` "
        "(or another 7B–14B for ~24GB Mac). Optional remote: point OLLAMA_BASE_URL "
        "at a Windows RTX 3070 host later."
    )


def _ollama_chat(system: str, user: str, cfg: dict[str, str]) -> str:
    url = f"{cfg['ollama_base_url']}/api/chat"
    payload = {
        "model": cfg["ollama_model"],
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "options": {"temperature": 0.3},
    }
    with httpx.Client(timeout=180.0) as client:
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


def complete_json(system: str, user: str) -> dict[str, Any]:
    """
    Call the configured LLM and parse a JSON object response.

    Raises RuntimeError with a user-facing message on setup/network failures.
    """
    cfg = llm_config()
    provider = cfg["provider"]
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

    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to salvage the first {...} block
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start : end + 1])
        else:
            raise RuntimeError(f"LLM did not return valid JSON. Preview: {text[:400]}") from None
    if not isinstance(data, dict):
        raise RuntimeError("LLM JSON root must be an object")
    return data

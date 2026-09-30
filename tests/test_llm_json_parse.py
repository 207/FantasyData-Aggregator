from __future__ import annotations

import json

import pytest

from analysis.llm_client import (
    LLMParseError,
    _parse_json_object,
    complete_json,
)


VALID = (
    '{"trades":[],"waivers":[{"add":"A","drop":null,"position":"RB","why":"x"}],'
    '"start_sit":[],"notes":"ok"}'
)


def test_parse_strips_markdown_fences():
    fenced = f"```json\n{VALID}\n```"
    parsed = _parse_json_object(fenced)
    assert parsed["notes"] == "ok"
    assert parsed["waivers"][0]["add"] == "A"


def test_parse_repairs_trailing_commas():
    messy = """
    {
      "trades": [],
      "waivers": [
        {"add": "A", "drop": null, "position": "RB", "why": "x"},
      ],
      "start_sit": [],
      "notes": "ok",
    }
    """
    parsed = _parse_json_object(messy)
    assert parsed["notes"] == "ok"
    assert len(parsed["waivers"]) == 1


def test_parse_extracts_object_from_prose():
    wrapped = f"Sure, here you go:\n{VALID}\nHope that helps!"
    parsed = _parse_json_object(wrapped)
    assert "trades" in parsed


def test_parse_closes_truncated_object():
    truncated = (
        '{"trades":[],"waivers":[{"add":"A","drop":null,"position":"RB","why":"x"}],'
        '"start_sit":[],"notes":"ok"'
    )
    parsed = _parse_json_object(truncated)
    assert parsed["notes"] == "ok"


def test_parse_never_raises_json_decode_error():
    with pytest.raises(LLMParseError) as ei:
        _parse_json_object("{not json at all,,,")
    assert isinstance(ei.value, LLMParseError)
    assert ei.value.raw.startswith("{not json")


def test_parse_expecting_comma_glitch_trailing_comma():
    # Mimics Gemini "Expecting ',' delimiter" cases that are really trailing commas.
    bad = """{
  "trades": [],
  "waivers": [
    {
      "add": "Player A",
      "drop": "Player B",
      "position": "WR",
      "why": "upside"
    },
  ],
  "start_sit": [],
  "notes": "test"
}"""
    # Raw json.loads fails; our parser repairs.
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad)
    parsed = _parse_json_object(bad)
    assert parsed["waivers"][0]["add"] == "Player A"


def test_complete_json_retries_on_parse_failure(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_JSON_PARSE_RETRIES", "2")

    calls = {"n": 0}
    # Unterminated string — local repair cannot close this.
    bad = '{"trades": [{"you_get": "oops'
    good = (
        '{"trades":[],"waivers":[],"start_sit":[],"notes":"recovered"}'
    )

    def fake_dispatch(system: str, user: str, cfg: dict) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return bad
        return good

    monkeypatch.setattr("analysis.llm_client._dispatch_chat", fake_dispatch)
    data, raw = complete_json("sys", "user")
    assert calls["n"] == 2
    assert data["notes"] == "recovered"
    assert raw == good



def test_complete_json_raises_parse_error_with_raw(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_JSON_PARSE_RETRIES", "1")

    def always_bad(system: str, user: str, cfg: dict) -> str:
        return "{broken"

    monkeypatch.setattr("analysis.llm_client._dispatch_chat", always_bad)
    with pytest.raises(LLMParseError) as ei:
        complete_json("sys", "user")
    assert ei.value.raw == "{broken"

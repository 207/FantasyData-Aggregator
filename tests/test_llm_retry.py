from __future__ import annotations

from analysis.llm_client import (
    _call_with_backoff,
    _is_retryable_llm_error,
    _retry_settings,
)


class _Fake503(Exception):
    def __init__(self, code: int = 503, message: str = "high demand"):
        self.code = code
        super().__init__(f"{code} UNAVAILABLE. {message}")


def test_retryable_detects_gemini_high_demand():
    assert _is_retryable_llm_error(
        Exception(
            "503 UNAVAILABLE. {'error': {'message': 'This model is currently experiencing high demand.'}}"
        )
    )
    assert _is_retryable_llm_error(_Fake503())
    assert not _is_retryable_llm_error(Exception("GEMINI_API_KEY is not set"))


def test_call_with_backoff_doubles_wait(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setenv("LLM_RETRY_MAX", "4")
    monkeypatch.setenv("LLM_RETRY_BASE_SECONDS", "2")
    monkeypatch.setattr("analysis.llm_client.time.sleep", lambda s: sleeps.append(s))

    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 4:
            raise _Fake503()
        return "ok"

    assert _call_with_backoff(flaky, label="test") == "ok"
    assert attempts["n"] == 4
    assert sleeps == [2.0, 4.0, 8.0]


def test_retry_settings_defaults():
    max_a, base = _retry_settings()
    assert max_a >= 1
    assert base >= 0.5

from __future__ import annotations

"""Generate trade / waiver / start-sit recommendations via LLM."""

from typing import Any

from analysis.llm_client import complete_json, describe_setup
from analysis.llm_context import (
    SYSTEM_PROMPT,
    build_recommendation_context,
    build_user_prompt,
    compact_context_for_llm,
)
from analysis.weakness import TRADE_POS

NEVER_TRADE = frozenset({"QB", "DST", "K"})


def _pos_of(name: str, context: dict[str, Any]) -> str | None:
    name_l = (name or "").strip().lower()
    if not name_l:
        return None
    your = context.get("your_team", {}).get("roster") or []
    for p in your:
        if (p.get("name") or "").lower() == name_l:
            return p.get("position")
    for roster in (context.get("other_rosters") or {}).values():
        for p in roster:
            if (p.get("name") or "").lower() == name_l:
                return p.get("position")
    for fa in context.get("free_agents_skill") or []:
        if (fa.get("name") or "").lower() == name_l:
            return fa.get("position")
    return None


def _filter_trades(trades: list[dict], context: dict[str, Any]) -> list[dict]:
    cleaned: list[dict] = []
    for t in trades or []:
        if not isinstance(t, dict):
            continue
        get = t.get("you_get") or []
        send = t.get("you_send") or []
        if isinstance(get, str):
            get = [get]
        if isinstance(send, str):
            send = [send]
        names = list(get) + list(send)
        bad = False
        for n in names:
            pos = _pos_of(str(n), context)
            if pos in NEVER_TRADE:
                bad = True
                break
        if bad:
            continue
        cleaned.append(
            {
                "you_get": [str(x) for x in get],
                "you_send": [str(x) for x in send],
                "partner": t.get("partner") or "",
                "why": t.get("why") or "",
            }
        )
    return cleaned[:5]


def generate_recommendations(
    *,
    team_name: str,
    hunt_positions: list[str] | None,
    meta: Any,
    rosters: list[Any],
    players: dict[str, Any],
    standings: list[Any],
    rankings: list[Any],
    free_agents: list[dict[str, Any]],
    news_items: list[Any],
    include_start_sit: bool = True,
) -> dict[str, Any]:
    """
    Returns {
      ok, error, context (full/untruncated), context_sent (compact),
      raw_response, result, setup
    }.
    On LLM failure, still returns full context so the UI can export/paste.
    """
    hunt = [p for p in (hunt_positions or list(TRADE_POS)) if p in TRADE_POS] or list(TRADE_POS)
    context = build_recommendation_context(
        team_name=team_name,
        hunt_positions=hunt,
        meta=meta,
        rosters=rosters,
        players=players,
        standings=standings,
        rankings=rankings,
        free_agents=free_agents,
        news_items=news_items,
        include_start_sit=include_start_sit,
    )
    context_sent = compact_context_for_llm(context)
    setup = describe_setup()
    try:
        raw, raw_text = complete_json(SYSTEM_PROMPT, build_user_prompt(context, compact=True))
    except RuntimeError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "context": context,
            "context_sent": context_sent,
            "raw_response": None,
            "result": None,
            "setup": setup,
        }

    result = {
        "trades": _filter_trades(raw.get("trades") or [], context),
        "waivers": (raw.get("waivers") or [])[:8],
        "start_sit": (raw.get("start_sit") or [])[:5] if include_start_sit else [],
        "notes": raw.get("notes") or "",
    }
    return {
        "ok": True,
        "error": None,
        "context": context,
        "context_sent": context_sent,
        "raw_response": raw_text,
        "result": result,
        "setup": setup,
    }

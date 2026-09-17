from __future__ import annotations

"""Waiver helpers reduced to FA list shaping for LLM context / UI preview.

Analytical waiver scoring was removed — recommendations come from the LLM.
"""

from typing import Any

from analysis.weakness import TRADE_POS
from ingestion.positions import normalize_position


def skill_free_agents(
    free_agents: list[dict[str, Any]] | None,
    hunt_positions: list[str] | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Filter FA pool to hunt positions (default RB/WR/TE) for UI + LLM."""
    hunt = [p for p in (hunt_positions or list(TRADE_POS)) if p in TRADE_POS] or list(TRADE_POS)
    hunt_set = set(hunt)
    out: list[dict[str, Any]] = []
    for fa in free_agents or []:
        pos = normalize_position(fa.get("position") or "")
        if pos not in hunt_set:
            continue
        out.append(
            {
                "player": fa.get("name"),
                "position": pos,
                "nfl_team": fa.get("nfl_team") or "",
                "player_id": fa.get("player_id") or "",
            }
        )
        if len(out) >= limit:
            break
    return out

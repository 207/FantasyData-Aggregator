from __future__ import annotations

"""Orchestrate league + rankings refresh into one payload for SQLite."""

from typing import Any

from ingestion.consensus import build_consensus, normalize_player_name
from ingestion.espn_adapter import fetch_league as fetch_league_core
from ingestion.fantasypros_adapter import fetch_fantasypros_rankings
from ingestion.positions import normalize_position
from ingestion.sleeper_adapter import fetch_sleeper_rankings


def _attach_player_ids(rankings: list[dict[str, Any]], players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[tuple[str, str], str] = {}
    for p in players:
        pos = normalize_position(p.get("position") or "")
        key = (normalize_player_name(p.get("name") or "", pos), pos)
        if key[0]:
            by_name[key] = str(p["player_id"])

    out = []
    for row in rankings:
        pos = normalize_position(row.get("position") or "")
        key = (normalize_player_name(row.get("name") or "", pos), pos)
        pid = by_name.get(key) or row.get("name") or ""
        out.append({**row, "player_id": pid})
    return out


def fetch_league(force_demo: bool = False) -> dict[str, Any]:
    """Pull ESPN/demo league plus FantasyPros/Sleeper consensus rankings."""
    payload = fetch_league_core(force_demo=force_demo)
    week = int(payload.get("current_week") or 1)

    fp = fetch_fantasypros_rankings(week=week)
    sl = fetch_sleeper_rankings(week=week)

    logs = list(payload.get("refresh_logs") or [])
    logs.append(fp["log"])
    logs.append(sl["log"])

    consensus = build_consensus([fp.get("rankings") or [], sl.get("rankings") or []], week=week)
    # Store both consensus and raw sources for transparency
    all_rows = list(consensus)
    for row in fp.get("rankings") or []:
        all_rows.append(row)
    for row in sl.get("rankings") or []:
        all_rows.append(row)

    all_rows = _attach_player_ids(all_rows, payload.get("players") or [])
    payload["rankings"] = all_rows
    payload["consensus_rankings"] = [r for r in all_rows if r.get("source") == "consensus"]
    payload["trending"] = sl.get("trending") or []
    # Demo/ESPN free agents stay on the league payload; also expose for UI.
    payload.setdefault("free_agents", payload.get("free_agents") or [])
    payload["refresh_logs"] = logs
    if consensus:
        logs.append(
            {
                "source": "consensus",
                "status": "ok",
                "message": f"Built consensus board with {len(consensus)} players.",
            }
        )
    else:
        logs.append(
            {
                "source": "consensus",
                "status": "error",
                "message": "No consensus rankings could be built.",
            }
        )
    return payload

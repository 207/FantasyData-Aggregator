from __future__ import annotations

"""Orchestrate league + rankings + news refresh into one payload for SQLite."""

from typing import Any

from ingestion.consensus import build_consensus_both, fusion_method, normalize_player_name
from ingestion.espn_adapter import fetch_league as fetch_league_core
from ingestion.espn_rankings import rankings_from_espn_players
from ingestion.fantasypros_adapter import fetch_fantasypros_both
from ingestion.news_adapter import fetch_news_and_injuries
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
        pid = by_name.get(key) or row.get("player_id") or row.get("name") or ""
        out.append({**row, "player_id": pid})
    return out


def fetch_league(force_demo: bool = False) -> dict[str, Any]:
    """Pull ESPN/demo league plus multi-source weekly/ROS rankings and news."""
    payload = fetch_league_core(force_demo=force_demo)
    week = int(payload.get("current_week") or 1)
    players = payload.get("players") or []

    fp = fetch_fantasypros_both(week=week)
    sl = fetch_sleeper_rankings(week=week)

    espn_weekly = rankings_from_espn_players(players, week=week, horizon="weekly")
    espn_ros = rankings_from_espn_players(players, week=week, horizon="ros")
    espn_rows = espn_weekly + espn_ros
    espn_log = {
        "source": "espn_projections",
        "status": "ok" if espn_rows else "stale",
        "message": (
            f"Built {len(espn_weekly)} weekly + {len(espn_ros)} ROS ranks from ESPN projected points."
            if espn_rows
            else "No ESPN projected points on roster/FA — third source skipped."
        ),
    }

    news_bundle = fetch_news_and_injuries(players)

    logs = list(payload.get("refresh_logs") or [])
    logs.extend(fp.get("logs") or [])
    logs.append(sl["log"])
    logs.append(espn_log)
    logs.extend(news_bundle.get("logs") or [])

    source_lists = [
        fp.get("rankings") or [],
        sl.get("rankings") or [],
        espn_rows,
    ]
    method = fusion_method()
    consensus = build_consensus_both(source_lists, week=week, method=method)

    all_rows = list(consensus)
    for rows in source_lists:
        all_rows.extend(rows)

    all_rows = _attach_player_ids(all_rows, players)
    payload["rankings"] = all_rows
    payload["news"] = news_bundle.get("news") or []
    payload["trending"] = sl.get("trending") or []
    payload.setdefault("free_agents", payload.get("free_agents") or [])
    payload["refresh_logs"] = logs

    ros_n = sum(1 for r in consensus if r.get("horizon") == "ros")
    wk_n = sum(1 for r in consensus if r.get("horizon") == "weekly")
    if consensus:
        logs.append(
            {
                "source": "consensus",
                "status": "ok",
                "message": (
                    f"Fused boards ({method}): {ros_n} ROS + {wk_n} weekly players "
                    "(FantasyPros + Sleeper + ESPN when present)."
                ),
            }
        )
    else:
        logs.append(
            {
                "source": "consensus",
                "status": "error",
                "message": "No fused rankings could be built.",
            }
        )
    return payload

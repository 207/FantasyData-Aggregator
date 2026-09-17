from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ingestion.demo_data import build_demo_payload
from ingestion.positions import normalize_lineup_slot, normalize_position

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
ENV_PATH = CONFIG_DIR / ".env"


def load_config() -> dict[str, str]:
    load_dotenv(ENV_PATH)
    return {
        "league_id": os.getenv("LEAGUE_ID", "").strip(),
        "year": os.getenv("YEAR", "2025").strip(),
        "swid": os.getenv("SWID", "").strip(),
        "espn_s2": os.getenv("ESPN_S2", "").strip(),
        "team_name": os.getenv("TEAM_NAME", "").strip(),
        "rankings_mode": os.getenv("RANKINGS_MODE", "live").strip().lower() or "live",
    }


def espn_configured(cfg: dict[str, str] | None = None) -> bool:
    cfg = cfg or load_config()
    return bool(cfg["league_id"] and cfg["swid"] and cfg["espn_s2"])


def fetch_espn_league(cfg: dict[str, str] | None = None) -> dict[str, Any]:
    """Pull league snapshot via espn_api. Raises on auth/network failure."""
    cfg = cfg or load_config()
    if not espn_configured(cfg):
        raise ValueError("ESPN credentials incomplete")

    from espn_api.football import League  # lazy import

    year = int(cfg["year"] or 2025)
    league = League(
        league_id=int(cfg["league_id"]),
        year=year,
        espn_s2=cfg["espn_s2"],
        swid=cfg["swid"],
    )

    current_week = int(getattr(league, "current_week", 1) or 1)
    players: dict[str, dict] = {}
    rosters: list[dict] = []
    standings: list[dict] = []
    team_names: list[str] = []

    for team in league.teams:
        team_id = str(team.team_id)
        team_name = team.team_name
        team_names.append(team_name)
        standings.append(
            {
                "team_id": team_id,
                "team_name": team_name,
                "wins": int(getattr(team, "wins", 0) or 0),
                "losses": int(getattr(team, "losses", 0) or 0),
                "ties": int(getattr(team, "ties", 0) or 0),
                "points_for": float(getattr(team, "points_for", 0) or 0),
                "points_against": float(getattr(team, "points_against", 0) or 0),
                "week": current_week,
            }
        )

        for player in getattr(team, "roster", []) or []:
            pid = str(getattr(player, "playerId", None) or getattr(player, "id", player.name))
            # ESPN returns defense as "D/ST"; normalize to DST so grades/UI match.
            pos = normalize_position(getattr(player, "position", "") or "")
            nfl = getattr(player, "proTeam", "") or getattr(player, "pro_team", "") or ""
            proj = getattr(player, "projected_total_points", None)
            if proj is None:
                proj = getattr(player, "projected_avg_points", None)
            if proj is None:
                proj = getattr(player, "projected_points", None)
            entry = {
                "player_id": pid,
                "name": player.name,
                "position": pos,
                "nfl_team": nfl,
            }
            try:
                if proj is not None:
                    entry["projected_points"] = float(proj)
            except (TypeError, ValueError):
                pass
            players[pid] = entry
            lineup_slot_id = getattr(player, "lineupSlot", None)
            if lineup_slot_id is None:
                lineup_slot_id = getattr(player, "slot_position", None)
            slot, lineup = normalize_lineup_slot(lineup_slot_id, pos)
            rosters.append(
                {
                    "team_id": team_id,
                    "team_name": team_name,
                    "player_id": pid,
                    "week": current_week,
                    "slot": slot,
                    "lineup_slot": lineup,
                }
            )

    matchups: list[dict] = []
    try:
        box = league.box_scores(current_week)
        for game in box:
            home = game.home_team
            away = game.away_team
            if home is None or away is None:
                continue
            matchups.append(
                {
                    "week": current_week,
                    "home_team_id": str(home.team_id),
                    "home_team_name": home.team_name,
                    "home_score": float(getattr(game, "home_score", 0) or 0),
                    "away_team_id": str(away.team_id),
                    "away_team_name": away.team_name,
                    "away_score": float(getattr(game, "away_score", 0) or 0),
                }
            )
        scoreboard_status = "ok"
        scoreboard_msg = f"Loaded {len(matchups)} matchups for week {current_week}."
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        scoreboard_status = "error"
        scoreboard_msg = f"Matchups unavailable: {exc}"

    free_agents: list[dict] = []
    fa_status, fa_msg = "ok", ""
    try:
        fa_list = league.free_agents(size=80) or []
        for player in fa_list:
            pid = str(getattr(player, "playerId", None) or getattr(player, "id", player.name))
            pos = normalize_position(getattr(player, "position", "") or "")
            nfl = getattr(player, "proTeam", "") or getattr(player, "pro_team", "") or ""
            entry = {
                "player_id": pid,
                "name": player.name,
                "position": pos,
                "nfl_team": nfl,
            }
            free_agents.append(entry)
            # Keep FA in the global player map so name→id joins still work.
            players.setdefault(pid, entry)
        fa_msg = f"Loaded {len(free_agents)} free agents."
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        fa_status = "error"
        fa_msg = f"Free agents unavailable: {exc}"

    settings = getattr(league, "settings", None)
    scoring = {}
    roster_slots = {}
    league_name = getattr(settings, "name", None) or f"ESPN League {cfg['league_id']}"
    if settings is not None:
        scoring = {
            "reg_season_count": getattr(settings, "reg_season_count", None),
            "scoring_type": str(getattr(settings, "scoring_type", "")),
        }
        roster_slots = getattr(settings, "position_slot_counts", {}) or {}

    return {
        "league_id": str(cfg["league_id"]),
        "league_name": league_name,
        "year": year,
        "current_week": current_week,
        "source_mode": "espn",
        "scoring_settings": scoring,
        "roster_slots": roster_slots if isinstance(roster_slots, dict) else {},
        "team_names": team_names,
        "players": list(players.values()),
        "rosters": rosters,
        "standings": standings,
        "matchups": matchups,
        "free_agents": free_agents,
        "refresh_logs": [
            {
                "source": "espn",
                "status": "ok",
                "message": f"Synced {len(team_names)} teams, {len(players)} players.",
            },
            {"source": "espn_matchups", "status": scoreboard_status, "message": scoreboard_msg},
            {"source": "espn_free_agents", "status": fa_status, "message": fa_msg},
        ],
    }


def fetch_league(force_demo: bool = False) -> dict[str, Any]:
    """
    Prefer live ESPN when configured; otherwise (or on failure) return demo data.
    Always returns a complete payload suitable for SQLite upsert.
    """
    cfg = load_config()
    if force_demo or not espn_configured(cfg):
        payload = build_demo_payload()
        if cfg.get("team_name"):
            payload["preferred_team"] = cfg["team_name"]
        return payload

    try:
        payload = fetch_espn_league(cfg)
        if cfg.get("team_name"):
            payload["preferred_team"] = cfg["team_name"]
        return payload
    except Exception as exc:  # noqa: BLE001 — fall back to demo
        payload = build_demo_payload()
        payload["refresh_logs"] = [
            {
                "source": "espn",
                "status": "error",
                "message": f"ESPN pull failed ({exc}); showing demo league instead.",
            },
            {"source": "demo", "status": "ok", "message": "Demo fallback loaded."},
        ]
        if cfg.get("team_name"):
            payload["preferred_team"] = cfg["team_name"]
        return payload

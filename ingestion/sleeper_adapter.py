from __future__ import annotations

"""Sleeper public API adapter — player metadata ranks + trending adds."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from ingestion.positions import normalize_position

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
load_dotenv(CONFIG_DIR / ".env")

SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_TRENDING_URL = "https://api.sleeper.app/v1/players/nfl/trending/add"


def _enabled() -> bool:
    return (os.getenv("SLEEPER_ENABLED", "true") or "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def fetch_sleeper_rankings(week: int = 1, limit: int = 400) -> dict[str, Any]:
    """
    Build positional ranks from Sleeper `search_rank` (ADP-ish ordering).

    Free public API — no auth. Falls back to empty list with an error log.
    """
    if not _enabled():
        return {
            "rankings": [],
            "trending": [],
            "log": {
                "source": "sleeper",
                "status": "stale",
                "message": "Sleeper disabled via SLEEPER_ENABLED.",
            },
        }

    mode = (os.getenv("RANKINGS_MODE", "live") or "live").strip().lower()
    if mode == "mock":
        return {
            "rankings": [],
            "trending": [],
            "log": {
                "source": "sleeper",
                "status": "ok",
                "message": "RANKINGS_MODE=mock — skipped live Sleeper pull.",
            },
        }

    pulled = datetime.now(timezone.utc)
    try:
        with httpx.Client(timeout=60.0, headers={"User-Agent": "FantasyAnalysis/0.2"}) as client:
            players_resp = client.get(SLEEPER_PLAYERS_URL)
            players_resp.raise_for_status()
            players = players_resp.json()
            trending: list[dict[str, Any]] = []
            try:
                trend_resp = client.get(SLEEPER_TRENDING_URL, params={"lookback_hours": 24, "limit": 25})
                if trend_resp.status_code == 200:
                    trending = trend_resp.json() or []
            except Exception:  # noqa: BLE001
                trending = []

        by_pos: dict[str, list[tuple[int, dict]]] = {
            "QB": [],
            "RB": [],
            "WR": [],
            "TE": [],
            "K": [],
            "DST": [],
        }
        for _sid, pdata in (players or {}).items():
            if not isinstance(pdata, dict):
                continue
            if pdata.get("active") is False:
                continue
            pos = normalize_position(pdata.get("position") or "")
            if pos not in by_pos:
                continue
            name = pdata.get("full_name") or pdata.get("last_name")
            team = pdata.get("team") or ""
            if pos == "DST":
                # Sleeper defenses usually have no full_name — synthesize ESPN-style label.
                name = name or (f"{team} D/ST" if team else None)
            if not name:
                continue
            search_rank = pdata.get("search_rank")
            # DEF often lacks search_rank; keep team-based entries ordered later by team code.
            if search_rank is None:
                if pos != "DST" or not team:
                    continue
                try:
                    sr = 10_000 + abs(hash(team)) % 1000
                except Exception:  # noqa: BLE001
                    continue
            else:
                try:
                    sr = int(search_rank)
                except (TypeError, ValueError):
                    continue
            by_pos[pos].append((sr, {"name": name, "position": pos, "sleeper_id": str(pdata.get("player_id", ""))}))

        rankings: list[dict[str, Any]] = []
        for pos, items in by_pos.items():
            items.sort(key=lambda t: t[0])
            for i, (_sr, meta) in enumerate(items[:limit], start=1):
                rankings.append(
                    {
                        "name": meta["name"],
                        "position": pos,
                        "rank": i,
                        "tier": (i - 1) // 6 + 1,
                        "projected_points": None,
                        "source": "sleeper",
                        "week": week,
                        "pulled_at": pulled,
                        "external_id": meta.get("sleeper_id"),
                    }
                )

        trend_names = []
        for t in trending:
            pid = str(t.get("player_id", ""))
            pdata = (players or {}).get(pid) or {}
            nm = pdata.get("full_name")
            if nm:
                trend_names.append(nm)

        return {
            "rankings": rankings,
            "trending": trend_names,
            "log": {
                "source": "sleeper",
                "status": "ok",
                "message": f"Loaded {len(rankings)} Sleeper positional ranks"
                + (f"; {len(trend_names)} trending adds." if trend_names else "."),
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "rankings": [],
            "trending": [],
            "log": {
                "source": "sleeper",
                "status": "error",
                "message": f"Sleeper pull failed: {exc}",
            },
        }

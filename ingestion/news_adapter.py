from __future__ import annotations

"""News / injury flags — ESPN public news API + Sleeper injury_status."""

from datetime import datetime, timezone
from typing import Any

import httpx

from ingestion.consensus import normalize_player_name
from ingestion.positions import normalize_position

ESPN_NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"


def fetch_espn_news(limit: int = 50) -> dict[str, Any]:
    """
    Free ESPN site API — headlines for NFL. No auth.

    Documented source: site.api.espn.com (public).
    """
    pulled = datetime.now(timezone.utc)
    try:
        with httpx.Client(timeout=25.0, headers={"User-Agent": "FantasyAnalysis/0.4"}) as client:
            resp = client.get(ESPN_NEWS_URL, params={"limit": limit})
            resp.raise_for_status()
            data = resp.json()
        articles = data.get("articles") or []
        items: list[dict[str, Any]] = []
        for art in articles:
            headline = (art.get("headline") or art.get("description") or "").strip()
            if not headline:
                continue
            # Best-effort player linkage via athlete mentions
            player_name = ""
            player_id = ""
            for cat in art.get("categories") or []:
                if not isinstance(cat, dict):
                    continue
                if cat.get("type") == "athlete" or cat.get("id") == "athlete":
                    player_name = cat.get("description") or cat.get("name") or player_name
            items.append(
                {
                    "player_id": player_id or (player_name or headline[:40]),
                    "player_name": player_name,
                    "source": "espn_news",
                    "headline": headline,
                    "body": (art.get("description") or "")[:500],
                    "injury_flag": _flag_from_text(headline),
                    "published_at": art.get("published") or pulled.isoformat(),
                    "pulled_at": pulled,
                }
            )
        return {
            "news": items,
            "log": {
                "source": "espn_news",
                "status": "ok",
                "message": f"Loaded {len(items)} ESPN NFL news headlines (site.api.espn.com).",
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "news": [],
            "log": {
                "source": "espn_news",
                "status": "error",
                "message": f"ESPN news failed: {exc}",
            },
        }


def fetch_sleeper_injuries() -> dict[str, Any]:
    """Pull injury_status from Sleeper players map — free public API."""
    pulled = datetime.now(timezone.utc)
    try:
        with httpx.Client(timeout=60.0, headers={"User-Agent": "FantasyAnalysis/0.4"}) as client:
            resp = client.get(SLEEPER_PLAYERS_URL)
            resp.raise_for_status()
            players = resp.json() or {}
        items: list[dict[str, Any]] = []
        for pid, pdata in players.items():
            if not isinstance(pdata, dict):
                continue
            status = (pdata.get("injury_status") or "").strip()
            if not status:
                continue
            name = pdata.get("full_name") or ""
            if not name:
                continue
            pos = normalize_position(pdata.get("position") or "")
            items.append(
                {
                    "player_id": str(pid),
                    "player_name": name,
                    "position": pos,
                    "source": "sleeper_injury",
                    "headline": f"{name} ({pos}) — {status}",
                    "body": "",
                    "injury_flag": status.upper(),
                    "published_at": pulled.isoformat(),
                    "pulled_at": pulled,
                }
            )
        items.sort(key=lambda x: x["player_name"])
        return {
            "news": items,
            "log": {
                "source": "sleeper_injury",
                "status": "ok",
                "message": f"Loaded {len(items)} Sleeper injury flags.",
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "news": [],
            "log": {
                "source": "sleeper_injury",
                "status": "error",
                "message": f"Sleeper injuries failed: {exc}",
            },
        }


def _flag_from_text(text: str) -> str:
    t = (text or "").lower()
    for key in ("out", "doubtful", "questionable", "injured", "ir", "pup", "suspended"):
        if key in t:
            return key.upper()
    return "NEWS"


def attach_player_ids(news: list[dict[str, Any]], players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, str] = {}
    for p in players:
        pos = normalize_position(p.get("position") or "")
        key = normalize_player_name(p.get("name") or "", pos)
        if key:
            by_name[key] = str(p["player_id"])
    out = []
    for item in news:
        name = item.get("player_name") or ""
        pos = item.get("position") or ""
        key = normalize_player_name(name, pos)
        pid = by_name.get(key) or item.get("player_id") or name or "unknown"
        out.append({**item, "player_id": pid})
    return out


def fetch_news_and_injuries(players: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Combine ESPN headlines + Sleeper injury statuses."""
    espn = fetch_espn_news()
    sleeper = fetch_sleeper_injuries()
    combined = list(espn.get("news") or []) + list(sleeper.get("news") or [])
    if players:
        combined = attach_player_ids(combined, players)
    return {
        "news": combined,
        "logs": [espn["log"], sleeper["log"]],
    }

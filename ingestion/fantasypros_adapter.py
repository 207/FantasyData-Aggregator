from __future__ import annotations

"""FantasyPros rankings adapter — live scrape with mock fallback."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from ingestion.positions import normalize_position

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
load_dotenv(CONFIG_DIR / ".env")

# ROS / season-long consensus. Override via FANTASYPROS_RANKINGS_URL.
DEFAULT_FP_ROS_URL = "https://www.fantasypros.com/nfl/rankings/ros-ppr-overall.php"
# Weekly PPR overall. Override via FANTASYPROS_WEEKLY_URL.
DEFAULT_FP_WEEKLY_URL = "https://www.fantasypros.com/nfl/rankings/ppr.php"
# Legacy alias
DEFAULT_FP_URL = DEFAULT_FP_ROS_URL

# Sensible offline ranks used when scrape fails or RANKINGS_MODE=mock.
MOCK_RANKINGS: list[dict[str, Any]] = [
    {"name": "Josh Allen", "position": "QB", "rank": 1, "tier": 1},
    {"name": "Lamar Jackson", "position": "QB", "rank": 2, "tier": 1},
    {"name": "Jalen Hurts", "position": "QB", "rank": 3, "tier": 1},
    {"name": "Patrick Mahomes", "position": "QB", "rank": 4, "tier": 1},
    {"name": "Brock Purdy", "position": "QB", "rank": 12, "tier": 3},
    {"name": "Christian McCaffrey", "position": "RB", "rank": 1, "tier": 1},
    {"name": "Bijan Robinson", "position": "RB", "rank": 2, "tier": 1},
    {"name": "Jahmyr Gibbs", "position": "RB", "rank": 3, "tier": 1},
    {"name": "Saquon Barkley", "position": "RB", "rank": 4, "tier": 1},
    {"name": "Breece Hall", "position": "RB", "rank": 8, "tier": 2},
    {"name": "David Montgomery", "position": "RB", "rank": 22, "tier": 4},
    {"name": "James Cook", "position": "RB", "rank": 14, "tier": 3},
    {"name": "Kyren Williams", "position": "RB", "rank": 10, "tier": 2},
    {"name": "Derrick Henry", "position": "RB", "rank": 6, "tier": 2},
    {"name": "Jonathan Taylor", "position": "RB", "rank": 7, "tier": 2},
    {"name": "Tyler Allgeier", "position": "RB", "rank": 45, "tier": 8},
    {"name": "Isiah Pacheco", "position": "RB", "rank": 18, "tier": 3},
    {"name": "Jaylen Warren", "position": "RB", "rank": 24, "tier": 4},
    {"name": "Zack Moss", "position": "RB", "rank": 32, "tier": 6},
    {"name": "Ja'Marr Chase", "position": "WR", "rank": 1, "tier": 1},
    {"name": "CeeDee Lamb", "position": "WR", "rank": 2, "tier": 1},
    {"name": "Justin Jefferson", "position": "WR", "rank": 3, "tier": 1},
    {"name": "Amon-Ra St. Brown", "position": "WR", "rank": 4, "tier": 1},
    {"name": "Malik Nabers", "position": "WR", "rank": 8, "tier": 2},
    {"name": "Rashee Rice", "position": "WR", "rank": 18, "tier": 3},
    {"name": "Tee Higgins", "position": "WR", "rank": 20, "tier": 4},
    {"name": "Puka Nacua", "position": "WR", "rank": 6, "tier": 2},
    {"name": "Nico Collins", "position": "WR", "rank": 12, "tier": 3},
    {"name": "Tyreek Hill", "position": "WR", "rank": 15, "tier": 3},
    {"name": "A.J. Brown", "position": "WR", "rank": 14, "tier": 3},
    {"name": "DK Metcalf", "position": "WR", "rank": 25, "tier": 5},
    {"name": "Courtland Sutton", "position": "WR", "rank": 22, "tier": 4},
    {"name": "Rome Odunze", "position": "WR", "rank": 28, "tier": 5},
    {"name": "Christian Kirk", "position": "WR", "rank": 35, "tier": 6},
    {"name": "Josh Downs", "position": "WR", "rank": 40, "tier": 7},
    {"name": "Michael Wilson", "position": "WR", "rank": 55, "tier": 9},
    {"name": "Travis Kelce", "position": "TE", "rank": 3, "tier": 1},
    {"name": "Trey McBride", "position": "TE", "rank": 1, "tier": 1},
    {"name": "Sam LaPorta", "position": "TE", "rank": 4, "tier": 2},
    {"name": "Mark Andrews", "position": "TE", "rank": 6, "tier": 2},
    {"name": "Dallas Goedert", "position": "TE", "rank": 10, "tier": 2},
    {"name": "Tucker Kraft", "position": "TE", "rank": 8, "tier": 2},
    {"name": "Isaiah Likely", "position": "TE", "rank": 18, "tier": 4},
    {"name": "Baker Mayfield", "position": "QB", "rank": 10, "tier": 2},
    {"name": "Bills D/ST", "position": "DST", "rank": 1, "tier": 1},
    {"name": "Ravens D/ST", "position": "DST", "rank": 2, "tier": 1},
    {"name": "49ers D/ST", "position": "DST", "rank": 3, "tier": 1},
    {"name": "Broncos D/ST", "position": "DST", "rank": 4, "tier": 1},
    {"name": "Eagles D/ST", "position": "DST", "rank": 5, "tier": 2},
    {"name": "Texans D/ST", "position": "DST", "rank": 6, "tier": 2},
    {"name": "Steelers D/ST", "position": "DST", "rank": 8, "tier": 2},
    {"name": "Patriots D/ST", "position": "DST", "rank": 12, "tier": 3},
    {"name": "Titans D/ST", "position": "DST", "rank": 18, "tier": 4},
    {"name": "Justin Tucker", "position": "K", "rank": 5, "tier": 2},
    {"name": "Harrison Butker", "position": "K", "rank": 2, "tier": 1},
    {"name": "Brandon Aubrey", "position": "K", "rank": 1, "tier": 1},
    {"name": "Cairo Santos", "position": "K", "rank": 12, "tier": 3},
    {"name": "Tyler Loop", "position": "K", "rank": 15, "tier": 3},
]


def _mock_rows(week: int, horizon: str = "ros") -> list[dict[str, Any]]:
    pulled = datetime.now(timezone.utc)
    rows = []
    for item in MOCK_RANKINGS:
        # Slight weekly jitter so mock weekly ≠ ROS for demos
        rank = int(item["rank"])
        if horizon == "weekly":
            rank = max(1, rank + (hash(item["name"]) % 5) - 2)
        rows.append(
            {
                "name": item["name"],
                "position": normalize_position(item["position"]),
                "rank": rank,
                "tier": item.get("tier"),
                "projected_points": None,
                "source": "fantasypros_mock",
                "horizon": horizon,
                "week": week,
                "pulled_at": pulled,
            }
        )
    return _to_positional_ranks(rows)


def _parse_rankings_html(html: str, week: int, horizon: str = "ros") -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    # Prefer embedded ecrData JS object (current FantasyPros pages).
    embedded = _try_parse_ecr_data(html, week, horizon=horizon)
    if embedded:
        return embedded

    table = soup.select_one("table#ranking-table") or soup.select_one("table.player-table")
    if table is None:
        raise ValueError("FantasyPros rankings table/ecrData not found")

    pulled = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        rank_text = cells[0].get_text(" ", strip=True)
        if not rank_text or not re.match(r"^\d+", rank_text):
            continue
        rank = int(re.match(r"^(\d+)", rank_text).group(1))
        name_cell = cells[1]
        name_el = name_cell.select_one("a.player-name") or name_cell.select_one("a")
        name = (name_el.get_text(strip=True) if name_el else name_cell.get_text(" ", strip=True))
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            continue
        pos = ""
        for cell in cells[2:5]:
            t = cell.get_text(strip=True)
            if t in {"QB", "RB", "WR", "TE", "K", "DST", "D/ST", "DEF"}:
                pos = t
                break
            m = re.match(r"^(QB|RB|WR|TE|K|DST|D/ST|DEF)", t)
            if m:
                pos = m.group(1)
                break
        rows.append(
            {
                "name": name,
                "position": normalize_position(pos),
                "rank": rank,
                "tier": None,
                "projected_points": None,
                "source": "fantasypros",
                "horizon": horizon,
                "week": week,
                "pulled_at": pulled,
            }
        )
    if not rows:
        raise ValueError("FantasyPros table parsed but yielded 0 players")
    return rows


def _extract_js_object(text: str, marker: str) -> str | None:
    idx = text.find(marker)
    if idx < 0:
        return None
    start = text.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    quote = ""
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                in_str = False
            continue
        if ch in {'"', "'"}:
            in_str = True
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _try_parse_ecr_data(html: str, week: int, horizon: str = "ros") -> list[dict[str, Any]] | None:
    import json

    blob = _extract_js_object(html, "ecrData = ")
    if not blob:
        return None
    data = json.loads(blob)
    players = data.get("players") or []
    if not players:
        return None
    pulled = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for item in players:
        if not isinstance(item, dict):
            continue
        name = item.get("player_name") or item.get("playerName") or item.get("name")
        if not name:
            continue
        rank = int(item.get("rank_ecr") or item.get("ecrRank") or item.get("rank") or 0)
        if rank <= 0:
            continue
        pos_raw = item.get("player_positions") or item.get("player_position_id") or item.get("position") or ""
        if isinstance(pos_raw, str) and "," in pos_raw:
            pos_raw = pos_raw.split(",")[0]
        tier = item.get("tier")
        try:
            tier_i = int(tier) if tier is not None else None
        except (TypeError, ValueError):
            tier_i = None
        rows.append(
            {
                "name": name,
                "position": normalize_position(str(pos_raw)),
                "rank": rank,
                "tier": tier_i,
                "projected_points": None,
                "source": "fantasypros",
                "horizon": horizon,
                "week": week,
                "pulled_at": pulled,
            }
        )
    return rows or None


def _parse_embedded_json(text: str, week: int) -> list[dict[str, Any]]:
    """Legacy array-shaped embeds — kept for older page layouts."""
    import json

    pulled = datetime.now(timezone.utc)
    match = re.search(r"(?:ecrData|players|ranking_data)\s*=\s*(\[[\s\S]*?\]);", text)
    if not match:
        raise ValueError("No embedded FantasyPros JSON found")
    data = json.loads(match.group(1))
    rows = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            continue
        name = item.get("player_name") or item.get("playerName") or item.get("name")
        if not name:
            continue
        rank = int(item.get("rank_ecr") or item.get("ecrRank") or item.get("rank") or i)
        pos = normalize_position(item.get("player_positions") or item.get("position") or "")
        if "," in pos:
            pos = normalize_position(pos.split(",")[0])
        rows.append(
            {
                "name": name,
                "position": pos,
                "rank": rank,
                "tier": item.get("tier"),
                "projected_points": None,
                "source": "fantasypros",
                "week": week,
                "pulled_at": pulled,
            }
        )
    if not rows:
        raise ValueError("Embedded FantasyPros JSON empty")
    return rows


def _fp_url_for_horizon(horizon: str) -> str:
    if horizon == "weekly":
        return (
            os.getenv("FANTASYPROS_WEEKLY_URL", DEFAULT_FP_WEEKLY_URL).strip()
            or DEFAULT_FP_WEEKLY_URL
        )
    return (
        os.getenv("FANTASYPROS_RANKINGS_URL", DEFAULT_FP_ROS_URL).strip()
        or DEFAULT_FP_ROS_URL
    )


def fetch_fantasypros_rankings(
    week: int = 1,
    force_mock: bool = False,
    horizon: str = "ros",
) -> dict[str, Any]:
    """
    Fetch FantasyPros rankings for one horizon (ros | weekly).

    Returns {"rankings": [...], "log": {source,status,message}}.
    Live overall ECR is converted to positional ranks so it merges cleanly with Sleeper.
    """
    horizon = "weekly" if horizon == "weekly" else "ros"
    mode = (os.getenv("RANKINGS_MODE", "live") or "live").strip().lower()
    src_label = f"fantasypros_{horizon}"
    if force_mock or mode == "mock":
        rows = _mock_rows(week, horizon=horizon)
        return {
            "rankings": rows,
            "log": {
                "source": src_label,
                "status": "ok",
                "message": f"Mock FantasyPros {horizon} rankings loaded ({len(rows)} players).",
            },
        }

    url = _fp_url_for_horizon(horizon)
    try:
        with httpx.Client(timeout=25.0, follow_redirects=True, headers={"User-Agent": "FantasyAnalysis/0.4"}) as client:
            resp = client.get(url)
            resp.raise_for_status()
            rows = _parse_rankings_html(resp.text, week, horizon=horizon)
        for row in rows:
            row["horizon"] = horizon
            row["source"] = "fantasypros"
        rows = _to_positional_ranks(rows)
        return {
            "rankings": rows,
            "log": {
                "source": src_label,
                "status": "ok",
                "message": f"Scraped {len(rows)} FantasyPros {horizon} ranks.",
            },
        }
    except Exception as exc:  # noqa: BLE001
        rows = _mock_rows(week, horizon=horizon)
        return {
            "rankings": rows,
            "log": {
                "source": src_label,
                "status": "stale",
                "message": f"Live FantasyPros {horizon} failed ({exc}); using mock ({len(rows)}).",
            },
        }


def fetch_fantasypros_both(week: int = 1, force_mock: bool = False) -> dict[str, Any]:
    """Pull ROS + weekly FantasyPros boards."""
    ros = fetch_fantasypros_rankings(week=week, force_mock=force_mock, horizon="ros")
    weekly = fetch_fantasypros_rankings(week=week, force_mock=force_mock, horizon="weekly")
    return {
        "rankings": list(ros.get("rankings") or []) + list(weekly.get("rankings") or []),
        "logs": [ros["log"], weekly["log"]],
    }


def _to_positional_ranks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-number ranks within each position (overall ECR → positional)."""
    by_pos: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pos = normalize_position(row.get("position") or "")
        if not pos:
            continue
        by_pos.setdefault(pos, []).append(row)
    out: list[dict[str, Any]] = []
    for pos, items in by_pos.items():
        items.sort(key=lambda r: int(r.get("rank") or 9999))
        for i, row in enumerate(items, start=1):
            out.append({**row, "position": pos, "rank": i, "tier": row.get("tier") or ((i - 1) // 6 + 1)})
    return out

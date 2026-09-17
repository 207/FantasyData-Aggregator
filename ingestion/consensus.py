from __future__ import annotations

"""Merge multi-source rankings into a consensus board keyed by normalized name."""

import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from ingestion.positions import normalize_position

# Weights when averaging ranks across sources.
SOURCE_WEIGHTS = {
    "fantasypros": 0.7,
    "fantasypros_mock": 0.7,
    "sleeper": 0.3,
    "espn": 0.35,
}

# Map city/franchise phrases → nickname used by ESPN ("Patriots D/ST").
_DST_ALIASES = {
    "arizona cardinals": "cardinals",
    "atlanta falcons": "falcons",
    "baltimore ravens": "ravens",
    "buffalo bills": "bills",
    "carolina panthers": "panthers",
    "chicago bears": "bears",
    "cincinnati bengals": "bengals",
    "cleveland browns": "browns",
    "dallas cowboys": "cowboys",
    "denver broncos": "broncos",
    "detroit lions": "lions",
    "green bay packers": "packers",
    "houston texans": "texans",
    "indianapolis colts": "colts",
    "jacksonville jaguars": "jaguars",
    "kansas city chiefs": "chiefs",
    "las vegas raiders": "raiders",
    "los angeles chargers": "chargers",
    "los angeles rams": "rams",
    "miami dolphins": "dolphins",
    "minnesota vikings": "vikings",
    "new england patriots": "patriots",
    "new orleans saints": "saints",
    "new york giants": "giants",
    "new york jets": "jets",
    "philadelphia eagles": "eagles",
    "pittsburgh steelers": "steelers",
    "san francisco 49ers": "49ers",
    "seattle seahawks": "seahawks",
    "tampa bay buccaneers": "buccaneers",
    "tennessee titans": "titans",
    "washington commanders": "commanders",
    "ari": "cardinals",
    "atl": "falcons",
    "bal": "ravens",
    "buf": "bills",
    "car": "panthers",
    "chi": "bears",
    "cin": "bengals",
    "cle": "browns",
    "dal": "cowboys",
    "den": "broncos",
    "det": "lions",
    "gb": "packers",
    "hou": "texans",
    "ind": "colts",
    "jax": "jaguars",
    "jac": "jaguars",
    "kc": "chiefs",
    "lv": "raiders",
    "lac": "chargers",
    "lar": "rams",
    "mia": "dolphins",
    "min": "vikings",
    "ne": "patriots",
    "no": "saints",
    "nyg": "giants",
    "nyj": "jets",
    "phi": "eagles",
    "pit": "steelers",
    "sf": "49ers",
    "sea": "seahawks",
    "tb": "buccaneers",
    "ten": "titans",
    "was": "commanders",
    "wsh": "commanders",
}


def normalize_player_name(name: str, position: str | None = None) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = text.replace("'", "").replace(".", "")
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", text)
    text = re.sub(r"[^a-z0-9\s/]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("d/st", "dst").replace(" def", " dst")

    pos = normalize_position(position) if position else ""
    looks_dst = pos == "DST" or text.endswith(" dst") or text in _DST_ALIASES or text in set(_DST_ALIASES.values())
    if looks_dst:
        key = text.replace(" dst", "").strip()
        key = _DST_ALIASES.get(key, key)
        for nick in set(_DST_ALIASES.values()):
            if key == nick or key.endswith(" " + nick):
                key = nick
                break
        return f"{key} dst"
    return text




def build_consensus(
    source_rankings: list[list[dict[str, Any]]],
    week: int,
    horizon: str = "ros",
) -> list[dict[str, Any]]:
    """
    Average weighted ranks by normalized player name within each position + horizon.

    Each input row needs: name, position, rank, source. Optional horizon (default ros).
    """
    horizon = "weekly" if horizon == "weekly" else "ros"
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for rows in source_rankings:
        for row in rows:
            row_h = row.get("horizon") or "ros"
            if row_h != horizon:
                continue
            name = row.get("name") or ""
            pos = normalize_position(row.get("position") or "")
            if not name or not pos or pos in {"BE", "IR", "FLEX"}:
                continue
            key = (normalize_player_name(name, pos), pos)
            entry = buckets.setdefault(
                key,
                {
                    "name": name,
                    "position": pos,
                    "ranks": [],
                    "weights": [],
                    "sources": [],
                },
            )
            if pos == "DST" and "d/st" in name.lower():
                entry["name"] = name
            try:
                rank = int(row["rank"])
            except (KeyError, TypeError, ValueError):
                continue
            src = str(row.get("source") or "unknown")
            weight = float(SOURCE_WEIGHTS.get(src, 0.4))
            entry["ranks"].append(rank)
            entry["weights"].append(weight)
            if src not in entry["sources"]:
                entry["sources"].append(src)

    by_pos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pulled = datetime.now(timezone.utc)
    for entry in buckets.values():
        if not entry["ranks"]:
            continue
        wsum = sum(entry["weights"])
        avg = sum(r * w for r, w in zip(entry["ranks"], entry["weights"])) / wsum
        by_pos[entry["position"]].append(
            {
                "name": entry["name"],
                "position": entry["position"],
                "avg_rank": round(avg, 2),
                "sources": ",".join(entry["sources"]),
                "source": "consensus",
                "horizon": horizon,
                "week": week,
                "pulled_at": pulled,
            }
        )

    consensus: list[dict[str, Any]] = []
    for _pos, items in by_pos.items():
        items.sort(key=lambda x: x["avg_rank"])
        for i, item in enumerate(items, start=1):
            consensus.append({**item, "rank": i, "tier": (i - 1) // 6 + 1})
    return consensus


def build_consensus_both(
    source_rankings: list[list[dict[str, Any]]],
    week: int,
) -> list[dict[str, Any]]:
    return build_consensus(source_rankings, week, horizon="ros") + build_consensus(
        source_rankings, week, horizon="weekly"
    )


def index_rankings_by_name(rankings: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rankings:
        pos = normalize_position(row.get("position") or "")
        key = (normalize_player_name(row.get("name") or "", pos), pos)
        out[key] = row
    return out

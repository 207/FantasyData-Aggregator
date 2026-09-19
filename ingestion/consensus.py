from __future__ import annotations

"""Fuse multi-source rankings into one weekly + one ROS board.

Default method is Reciprocal Rank Fusion (RRF). Optional mean / median averaging
are available via FUSION_METHOD. Fused rows are stored with source=\"consensus\".
"""

import os
import re
import statistics
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from ingestion.positions import normalize_position

# Legacy weights kept for mean fusion when FUSION_METHOD=mean (weighted).
SOURCE_WEIGHTS = {
    "fantasypros": 0.7,
    "fantasypros_mock": 0.7,
    "sleeper": 0.3,
    "espn": 0.35,
}

# Classic Cormack/Clarke/Buettcher RRF constant (k=60).
DEFAULT_RRF_K = 60

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


def fusion_method() -> str:
    raw = (os.getenv("FUSION_METHOD", "rrf") or "rrf").strip().lower()
    if raw in {"mean", "avg", "average"}:
        return "mean"
    if raw in {"median", "med"}:
        return "median"
    return "rrf"


def rrf_k() -> int:
    try:
        return max(1, int(os.getenv("FUSION_RRF_K", str(DEFAULT_RRF_K)) or DEFAULT_RRF_K))
    except ValueError:
        return DEFAULT_RRF_K


def _bucket_source_ranks(
    source_rankings: list[list[dict[str, Any]]],
    horizon: str,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Group per-source ranks by (normalized_name, position) for one horizon."""
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
                    "by_source": {},
                },
            )
            if pos == "DST" and "d/st" in name.lower():
                entry["name"] = name
            try:
                rank = int(row["rank"])
            except (KeyError, TypeError, ValueError):
                continue
            src = str(row.get("source") or "unknown")
            # One rank per source (keep best / first)
            if src in entry["by_source"]:
                continue
            weight = float(SOURCE_WEIGHTS.get(src, 0.4))
            entry["ranks"].append(rank)
            entry["weights"].append(weight)
            entry["sources"].append(src)
            entry["by_source"][src] = rank
    return buckets


def _score_entry(entry: dict[str, Any], method: str, k: int) -> float:
    """Lower is better for mean/median; higher is better for RRF (we negate later)."""
    ranks = entry["ranks"]
    if not ranks:
        return float("inf")
    if method == "rrf":
        # Higher RRF score = better → return negative so ascending sort works.
        score = sum(1.0 / (k + r) for r in ranks)
        return -score
    if method == "median":
        return float(statistics.median(ranks))
    # mean (weighted)
    wsum = sum(entry["weights"]) or 1.0
    return sum(r * w for r, w in zip(ranks, entry["weights"])) / wsum


def build_consensus(
    source_rankings: list[list[dict[str, Any]]],
    week: int,
    horizon: str = "ros",
    method: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fuse per-source ranks into one positional board for the given horizon.

    Methods:
      - rrf (default): score = Σ 1/(k + rank_s); re-rank within position
      - mean: weighted average of ranks (legacy SOURCE_WEIGHTS)
      - median: median of ranks across sources

    Each input row needs: name, position, rank, source. Optional horizon (default ros).
    Output rows use source=\"consensus\" and include fusion_method + fusion_score.
    """
    horizon = "weekly" if horizon == "weekly" else "ros"
    method = (method or fusion_method()).lower()
    if method not in {"rrf", "mean", "median"}:
        method = "rrf"
    k = rrf_k()

    buckets = _bucket_source_ranks(source_rankings, horizon)
    by_pos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pulled = datetime.now(timezone.utc)

    for entry in buckets.values():
        if not entry["ranks"]:
            continue
        sort_key = _score_entry(entry, method, k)
        if method == "rrf":
            fusion_score = -sort_key  # positive RRF sum
            avg_rank = round(statistics.mean(entry["ranks"]), 2)
        elif method == "median":
            fusion_score = sort_key
            avg_rank = round(sort_key, 2)
        else:
            fusion_score = sort_key
            avg_rank = round(sort_key, 2)

        by_pos[entry["position"]].append(
            {
                "name": entry["name"],
                "position": entry["position"],
                "avg_rank": avg_rank,
                "fusion_score": round(fusion_score, 6),
                "fusion_method": method,
                "sources": ",".join(entry["sources"]),
                "source": "consensus",
                "horizon": horizon,
                "week": week,
                "pulled_at": pulled,
                "_sort": sort_key,
            }
        )

    consensus: list[dict[str, Any]] = []
    for _pos, items in by_pos.items():
        items.sort(key=lambda x: (x["_sort"], x["name"]))
        for i, item in enumerate(items, start=1):
            item.pop("_sort", None)
            consensus.append({**item, "rank": i, "tier": (i - 1) // 6 + 1})
    return consensus


def build_consensus_both(
    source_rankings: list[list[dict[str, Any]]],
    week: int,
    method: str | None = None,
) -> list[dict[str, Any]]:
    return build_consensus(source_rankings, week, horizon="ros", method=method) + build_consensus(
        source_rankings, week, horizon="weekly", method=method
    )


def index_rankings_by_name(rankings: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rankings:
        pos = normalize_position(row.get("position") or "")
        key = (normalize_player_name(row.get("name") or "", pos), pos)
        out[key] = row
    return out

from __future__ import annotations

"""Recommend waiver / free-agent pickups for selected hunt positions."""

from typing import Any, Sequence

from analysis.roster_grader import REPLACEMENT_RANK, grade_roster
from analysis.trade_finder import (
    CORE_POS,
    CORE_POS_SET,
    _is_stream_hole,
    _normalize_hunt_positions,
)
from ingestion.consensus import index_rankings_by_name, normalize_player_name
from ingestion.positions import normalize_position

SKILL_POS = {"QB", "RB", "WR", "TE", "DST", "K"}


def _waiver_need_positions(grades: list[dict]) -> list[str]:
    """Auto fallback: skill positions first; QB/DST/K only for clear holes."""
    by_pos = {g["position"]: g for g in grades}
    needs: list[str] = []
    for pos in CORE_POS:
        g = by_pos.get(pos)
        if g and g.get("grade") == "Weak":
            needs.append(pos)
    for pos in CORE_POS:
        if pos in needs:
            continue
        g = by_pos.get(pos)
        if g and g.get("grade") == "Average":
            needs.append(pos)
    for pos in ("QB", "DST", "K"):
        g = by_pos.get(pos)
        if g and _is_stream_hole(g):
            needs.append(pos)
    # Only stream Average DST/K when there is no skill-position need to shop.
    if not any(p in CORE_POS_SET for p in needs):
        for pos in ("DST", "K"):
            if pos in needs:
                continue
            g = by_pos.get(pos)
            if g and g.get("grade") in {"Weak", "Average"}:
                needs.append(pos)
    if needs:
        return needs
    return [g["position"] for g in grades if g.get("position") in CORE_POS_SET]


def _rostered_keys(rosters: list[Any], players: dict[str, Any]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for row in rosters:
        player = players.get(row.player_id)
        if not player:
            continue
        pos = normalize_position(getattr(player, "position", "") or "")
        if pos not in SKILL_POS:
            continue
        keys.add((normalize_player_name(player.name, pos), pos))
    return keys


def _best_on_roster(
    team_name: str,
    pos: str,
    rosters: list[Any],
    players: dict[str, Any],
    rank_index: dict,
) -> tuple[float | None, str | None]:
    best: float | None = None
    best_name: str | None = None
    for row in rosters:
        if row.team_name != team_name:
            continue
        player = players.get(row.player_id)
        if not player:
            continue
        if normalize_position(player.position) != pos:
            continue
        key = (normalize_player_name(player.name, pos), pos)
        hit = rank_index.get(key)
        if not hit:
            continue
        try:
            rank = float(hit.get("rank") or hit.get("avg_rank") or 0)
        except (TypeError, ValueError):
            continue
        if rank <= 0:
            continue
        if best is None or rank < best:
            best = rank
            best_name = player.name
    return best, best_name


def _free_agent_pool(
    rosters: list[Any],
    players: dict[str, Any],
    consensus_rankings: list[dict[str, Any]],
    free_agents: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """
    Build FA candidates from explicit free-agent rows plus consensus names
    that are not on any roster.
    """
    rostered = _rostered_keys(rosters, players)
    pool: dict[tuple[str, str], dict[str, Any]] = {}

    # Explicit FA list from ESPN/demo (may lack ranks — filled from consensus).
    for fa in free_agents or []:
        name = (fa.get("name") or "").strip()
        pos = normalize_position(fa.get("position") or "")
        if not name or pos not in SKILL_POS:
            continue
        key = (normalize_player_name(name, pos), pos)
        if key in rostered:
            continue
        pool[key] = {
            "name": name,
            "position": pos,
            "nfl_team": fa.get("nfl_team") or "",
            "player_id": str(fa.get("player_id") or name),
        }

    # Anyone on the consensus board who isn't rostered is also a FA candidate.
    for row in consensus_rankings:
        name = (row.get("name") or "").strip()
        pos = normalize_position(row.get("position") or "")
        if not name or pos not in SKILL_POS:
            continue
        key = (normalize_player_name(name, pos), pos)
        if key in rostered:
            continue
        entry = pool.setdefault(
            key,
            {
                "name": name,
                "position": pos,
                "nfl_team": "",
                "player_id": str(row.get("player_id") or name),
            },
        )
        entry.setdefault("name", name)

    return list(pool.values())


def find_waiver_pickups(
    team_name: str,
    rosters: list[Any],
    players: dict[str, Any],
    consensus_rankings: list[dict[str, Any]] | None = None,
    free_agents: list[dict[str, Any]] | None = None,
    trending_names: list[str] | None = None,
    limit: int = 15,
    hunt_positions: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Rank free agents at selected hunt positions (default RB/WR/TE).

    When `hunt_positions` is set, filter strictly to those slots — even if you
    already grade Strong there (still allow upgrades / depth). Auto mode falls
    back to weak/average skill needs. Boosts Sleeper trending adds.
    """
    consensus = consensus_rankings or []
    rank_index = index_rankings_by_name(consensus)
    grades = grade_roster(team_name, rosters, players, consensus)
    weak = {g["position"] for g in grades if g["grade"] == "Weak"}
    average = {g["position"] for g in grades if g["grade"] == "Average"}
    grades_by_pos = {g["position"]: g for g in grades}

    explicit = hunt_positions is not None
    if explicit:
        priority = _normalize_hunt_positions(hunt_positions)
    else:
        priority = _waiver_need_positions(grades)
    if not priority:
        priority = list(CORE_POS)

    trending_keys = {
        normalize_player_name(n, None) for n in (trending_names or []) if n
    }

    pool = _free_agent_pool(rosters, players, consensus, free_agents)
    my_best = {
        pos: _best_on_roster(team_name, pos, rosters, players, rank_index) for pos in priority
    }

    scored: list[dict[str, Any]] = []
    for fa in pool:
        pos = fa["position"]
        if pos not in priority:
            continue
        key = (normalize_player_name(fa["name"], pos), pos)
        hit = rank_index.get(key)
        if not hit:
            continue
        try:
            rank = float(hit.get("rank") or hit.get("avg_rank") or 0)
        except (TypeError, ValueError):
            continue
        if rank <= 0:
            continue

        ours, our_name = my_best.get(pos, (None, None))
        repl = float(REPLACEMENT_RANK.get(pos, 24))
        trending = normalize_player_name(fa["name"], pos) in trending_keys or (
            normalize_player_name(fa["name"], None) in trending_keys
        )

        # Skip FAs who don't improve your best (unless trending near replacement).
        if ours is not None and rank >= ours and not (trending and rank <= repl * 1.5):
            continue
        if ours is None and rank > repl * 1.5 and not trending:
            continue

        your_grade = grades_by_pos.get(pos, {}).get("grade", "—")
        if pos in weak:
            grade_label = "Weak"
        elif pos in average:
            grade_label = "Average"
        else:
            grade_label = your_grade or "Strong"

        if explicit:
            lead = f"Hunting {pos} (selected"
            if grade_label == "Strong":
                lead += "; roster already Strong — shopping upgrades/depth"
            else:
                lead += f"; grades {grade_label}"
            lead += "). "
        else:
            lead = f"Auto need at {pos} ({grade_label}). "

        if ours is None:
            why = (
                f"{lead}"
                f"{fa['name']} is a free agent at consensus #{int(rank)} "
                f"(replacement ~#{int(repl)})."
            )
        else:
            delta = int(ours - rank)
            why = (
                f"{lead}"
                f"Your best: {our_name} #{int(ours)}; "
                f"{fa['name']} is FA consensus #{int(rank)}"
                + (f" — {delta} spots better." if delta > 0 else ".")
            )
        if trending:
            why += " Trending as a Sleeper add in the last 24h."
        if rank <= repl:
            why += f" At/above replacement (~#{int(repl)})."

        # Lower rank is better; prioritize earlier need slots and trending.
        pri = priority.index(pos) if pos in priority else 99
        core_boost = 8 if pos in CORE_POS_SET else 0
        # Mild Weak boost — hunt selection is the primary filter now.
        score = rank + pri * 5 - (8 if trending else 0) - (2 if pos in weak else 0) - core_boost

        scored.append(
            {
                "player": fa["name"],
                "position": pos,
                "nfl_team": fa.get("nfl_team") or "—",
                "rank": int(rank),
                "your_best_rank": int(ours) if ours is not None else None,
                "your_best": our_name,
                "trending": trending,
                "why": why,
                "_score": score,
            }
        )

    scored.sort(key=lambda r: (r["_score"], r["rank"]))
    for row in scored:
        row.pop("_score", None)
    return scored[:limit]

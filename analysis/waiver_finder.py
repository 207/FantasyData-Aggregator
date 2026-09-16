from __future__ import annotations

"""Recommend waiver / free-agent pickups for weak roster spots."""

from typing import Any

from analysis.roster_grader import REPLACEMENT_RANK, grade_roster
from ingestion.consensus import index_rankings_by_name, normalize_player_name
from ingestion.positions import normalize_position

SKILL_POS = {"QB", "RB", "WR", "TE", "DST", "K"}


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
) -> list[dict[str, Any]]:
    """
    Rank free agents that help weak (then average) positions.

    Boosts Sleeper trending adds. Each row includes a full-sentence `why`.
    """
    consensus = consensus_rankings or []
    rank_index = index_rankings_by_name(consensus)
    grades = grade_roster(team_name, rosters, players, consensus)
    weak = [g["position"] for g in grades if g["grade"] == "Weak"]
    average = [g["position"] for g in grades if g["grade"] == "Average"]
    priority = weak + [p for p in average if p not in weak]
    if not priority:
        priority = list(SKILL_POS)

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

        # Skip FAs who don't improve you (unless trending and near replacement).
        if ours is not None and rank >= ours and not (trending and rank <= repl * 1.5):
            continue
        if ours is None and rank > repl * 1.5 and not trending:
            continue

        grade_label = "Weak" if pos in weak else ("Average" if pos in average else "ok")
        if ours is None:
            why = (
                f"Your {pos} grades {grade_label} with no ranked starter; "
                f"{fa['name']} is a free agent at consensus #{int(rank)} "
                f"(replacement ~#{int(repl)})."
            )
        else:
            delta = int(ours - rank)
            why = (
                f"Your {pos} grades {grade_label} (best: {our_name} #{int(ours)}); "
                f"{fa['name']} is FA consensus #{int(rank)}"
                + (f" — {delta} spots better." if delta > 0 else ".")
            )
        if trending:
            why += " Trending as a Sleeper add in the last 24h."
        if rank <= repl:
            why += f" At/above replacement (~#{int(repl)})."

        # Lower rank is better; prioritize weak positions and trending.
        pri = priority.index(pos) if pos in priority else 99
        score = rank + pri * 5 - (8 if trending else 0) - (5 if pos in weak else 0)

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

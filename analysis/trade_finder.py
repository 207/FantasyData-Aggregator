from __future__ import annotations

"""Find trade targets on other rosters that fill your weak positions."""

from collections import defaultdict
from typing import Any

from analysis.roster_grader import REPLACEMENT_RANK, grade_roster
from ingestion.consensus import index_rankings_by_name, normalize_player_name
from ingestion.positions import normalize_position

SKILL_POS = {"QB", "RB", "WR", "TE", "DST", "K"}


def _team_players(
    team_name: str,
    rosters: list[Any],
    players: dict[str, Any],
) -> list[tuple[Any, Any]]:
    out: list[tuple[Any, Any]] = []
    for row in rosters:
        if row.team_name != team_name:
            continue
        player = players.get(row.player_id)
        if not player:
            continue
        pos = normalize_position(getattr(player, "position", "") or "")
        if pos not in SKILL_POS:
            continue
        out.append((row, player))
    return out


def _rank_for(player: Any, rank_index: dict) -> float | None:
    pos = normalize_position(getattr(player, "position", "") or "")
    key = (normalize_player_name(player.name, pos), pos)
    hit = rank_index.get(key)
    if not hit:
        return None
    try:
        return float(hit.get("rank") or hit.get("avg_rank") or 0) or None
    except (TypeError, ValueError):
        return None


def _best_rank_at_pos(
    team_name: str,
    pos: str,
    rosters: list[Any],
    players: dict[str, Any],
    rank_index: dict,
) -> tuple[float | None, str | None]:
    best: float | None = None
    best_name: str | None = None
    for _row, player in _team_players(team_name, rosters, players):
        if normalize_position(player.position) != pos:
            continue
        rank = _rank_for(player, rank_index)
        if rank is None:
            continue
        if best is None or rank < best:
            best = rank
            best_name = player.name
    return best, best_name


def _pos_depth(team_name: str, pos: str, rosters: list[Any], players: dict[str, Any]) -> int:
    return sum(
        1
        for _row, player in _team_players(team_name, rosters, players)
        if normalize_position(player.position) == pos
    )


def _surplus_offer(
    my_team: str,
    their_team: str,
    need_pos: str,
    grades_by_team: dict[str, list[dict]],
    rosters: list[Any],
    players: dict[str, Any],
    rank_index: dict,
) -> str | None:
    """Suggest a surplus piece we can offer that fills one of their weak spots."""
    their_grades = {g["position"]: g for g in grades_by_team.get(their_team, [])}
    my_grades = {g["position"]: g for g in grades_by_team.get(my_team, [])}

    candidates: list[tuple[float, str, str]] = []
    for pos, grade in my_grades.items():
        if pos == need_pos:
            continue
        if grade.get("grade") != "Strong":
            continue
        their = their_grades.get(pos)
        if not their or their.get("grade") == "Strong":
            continue
        # Prefer offering our 2nd-best at the surplus position (keep the star).
        ranked: list[tuple[float, str]] = []
        for _row, player in _team_players(my_team, rosters, players):
            if normalize_position(player.position) != pos:
                continue
            r = _rank_for(player, rank_index)
            ranked.append((r if r is not None else 999.0, player.name))
        ranked.sort(key=lambda t: t[0])
        if len(ranked) < 2:
            continue
        offer_rank, offer_name = ranked[1]
        candidates.append((offer_rank, offer_name, pos))

    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    _rank, name, pos = candidates[0]
    their_grade = their_grades.get(pos, {}).get("grade", "Weak")
    return f"Offer surplus {pos} {name} (they grade {their_grade} at {pos})"


def find_trade_targets(
    team_name: str,
    rosters: list[Any],
    players: dict[str, Any],
    consensus_rankings: list[dict[str, Any]] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """
    Surface players on other teams who upgrade your weak positions.

    Prefers counterparts with positional surplus (depth ≥ 2) and attaches an
    optional offer hint from your Strong positions.
    """
    rank_index = index_rankings_by_name(consensus_rankings or [])
    my_grades = grade_roster(team_name, rosters, players, consensus_rankings)
    weak_pos = [g["position"] for g in my_grades if g["grade"] == "Weak"]
    if not weak_pos:
        # Fall back to Average spots so the tab still shows useful targets.
        weak_pos = [g["position"] for g in my_grades if g["grade"] == "Average"]

    team_names = sorted({r.team_name for r in rosters})
    grades_by_team = {
        t: grade_roster(t, rosters, players, consensus_rankings) for t in team_names
    }

    my_best: dict[str, tuple[float | None, str | None]] = {
        pos: _best_rank_at_pos(team_name, pos, rosters, players, rank_index) for pos in weak_pos
    }

    scored: list[dict[str, Any]] = []
    seen: set[str] = set()

    for other in team_names:
        if other == team_name:
            continue
        for _row, player in _team_players(other, rosters, players):
            pos = normalize_position(player.position)
            if pos not in weak_pos:
                continue
            pid = str(getattr(player, "player_id", player.name))
            if pid in seen:
                continue

            their_rank = _rank_for(player, rank_index)
            if their_rank is None:
                continue

            ours, our_name = my_best.get(pos, (None, None))
            repl = float(REPLACEMENT_RANK.get(pos, 24))

            # Must be a real upgrade vs our best, or fill an empty hole.
            if ours is not None and their_rank >= ours:
                continue
            if ours is None and their_rank > repl * 1.25:
                # Empty / unranked hole — only chase near-replacement talent.
                continue

            depth = _pos_depth(other, pos, rosters, players)
            delta = None if ours is None else round(ours - their_rank, 1)
            offer = _surplus_offer(
                team_name, other, pos, grades_by_team, rosters, players, rank_index
            )

            if ours is None:
                why = (
                    f"You have no ranked {pos}; {player.name} is consensus #{int(their_rank)} "
                    f"on {other} (replacement ~#{int(repl)})."
                )
            else:
                why = (
                    f"Your {pos} best is {our_name or '—'} at #{int(ours)}; "
                    f"{player.name} is #{int(their_rank)} on {other} "
                    f"(+{int(delta)} rank spots)."
                )
            if depth >= 2:
                why += f" {other} has {depth} {pos}s — surplus makes them likelier to deal."
            else:
                why += f" {other} is thin at {pos} ({depth}); may want overpay."
            if offer:
                why += f" {offer}."

            # Score: bigger upgrade first; slight boost when counterpart is deep.
            upgrade = (ours - their_rank) if ours is not None else (repl - their_rank + 10)
            score = upgrade + (3.0 if depth >= 2 else 0.0)

            scored.append(
                {
                    "player": player.name,
                    "position": pos,
                    "owner": other,
                    "rank": int(their_rank),
                    "your_best_rank": int(ours) if ours is not None else None,
                    "your_best": our_name,
                    "delta": delta,
                    "owner_depth": depth,
                    "offer_hint": offer or "—",
                    "why": why,
                    "_score": score,
                }
            )
            seen.add(pid)

    scored.sort(key=lambda r: (-r["_score"], r["rank"]))
    for row in scored:
        row.pop("_score", None)
    return scored[:limit]

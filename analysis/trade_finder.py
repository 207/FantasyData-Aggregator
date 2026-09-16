from __future__ import annotations

"""Find trade targets on other rosters that fill your weak positions."""

from typing import Any

from analysis.roster_grader import REPLACEMENT_RANK, grade_roster
from ingestion.consensus import index_rankings_by_name, normalize_player_name
from ingestion.positions import normalize_position

SKILL_POS = {"QB", "RB", "WR", "TE", "DST", "K"}

# Positions worth trading for in most leagues (starters + FLEX).
CORE_POS = ("RB", "WR", "TE")
CORE_POS_SET = frozenset(CORE_POS)

# Streamable / scarce slots — usually fixed on waivers, not trades.
STREAM_POS = frozenset({"QB", "DST", "K"})

# Target must clear this rank to be a trade-worthy stream upgrade (not a lateral).
STREAM_ELITE_RANK = {"QB": 8, "DST": 6, "K": 5}

# Own starter must be this far worse than replacement before we hunt stream trades.
STREAM_HOLE_FACTOR = 1.25

# Minimum rank-spot gain to bother trading for a stream position.
STREAM_MIN_DELTA = 5


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


def _is_stream_hole(grade: dict[str, Any]) -> bool:
    """True when QB/DST/K is a real hole — not a barely-below-replacement streamer."""
    pos = grade.get("position")
    if pos not in STREAM_POS:
        return False
    if grade.get("grade") != "Weak":
        return False
    repl = float(REPLACEMENT_RANK.get(pos, 12))
    best = grade.get("best_rank")
    if best is None:
        # No ranked starter (or empty) — real hole.
        return True
    try:
        return float(best) > repl * STREAM_HOLE_FACTOR
    except (TypeError, ValueError):
        return True


def _trade_need_positions(grades: list[dict[str, Any]]) -> list[str]:
    """
    Ordered positions to shop for.

    Prefer RB/WR/TE (Weak then Average — covers FLEX depth). Only add QB/DST/K
    when that slot is a clear hole; never let mild DST Weak drown out skill needs.
    """
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

    if needs:
        return needs

    # Stacked core — last resort: any Average (may include stream).
    return [g["position"] for g in grades if g.get("grade") == "Average"]


def _stream_target_ok(
    pos: str,
    their_rank: float,
    ours: float | None,
) -> bool:
    """Filter streaming-slot targets to meaningful upgrades only."""
    elite = float(STREAM_ELITE_RANK.get(pos, 8))
    if their_rank > elite:
        return False
    if ours is None:
        return their_rank <= elite
    if their_rank >= ours:
        return False
    return (ours - their_rank) >= STREAM_MIN_DELTA


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

    candidates: list[tuple[float, float, str, str]] = []
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
        # Prefer offering core surplus over streaming-slot surplus.
        core_penalty = 0.0 if pos in CORE_POS_SET else 50.0
        candidates.append((core_penalty, offer_rank, offer_name, pos))

    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1]))
    _pen, _rank, name, pos = candidates[0]
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
    Surface players on other teams who upgrade your roster construction needs.

    Prefers RB/WR/TE (Weak, then Average / FLEX depth). QB/DST/K only when that
    slot is a clear hole and the target is a meaningful upgrade. Prefers
    counterparts with positional surplus and attaches an offer hint from your
    Strong (preferably skill) positions.
    """
    rank_index = index_rankings_by_name(consensus_rankings or [])
    my_grades = grade_roster(team_name, rosters, players, consensus_rankings)
    weak_pos = {g["position"] for g in my_grades if g["grade"] == "Weak"}
    need_pos = _trade_need_positions(my_grades)
    if not need_pos:
        return []

    team_names = sorted({r.team_name for r in rosters})
    grades_by_team = {
        t: grade_roster(t, rosters, players, consensus_rankings) for t in team_names
    }

    my_best: dict[str, tuple[float | None, str | None]] = {
        pos: _best_rank_at_pos(team_name, pos, rosters, players, rank_index) for pos in need_pos
    }

    scored: list[dict[str, Any]] = []
    seen: set[str] = set()

    for other in team_names:
        if other == team_name:
            continue
        for _row, player in _team_players(other, rosters, players):
            pos = normalize_position(player.position)
            if pos not in need_pos:
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

            if pos in STREAM_POS and not _stream_target_ok(pos, their_rank, ours):
                continue

            depth = _pos_depth(other, pos, rosters, players)
            # Prefer trading from their surplus; for stream slots require depth
            # so we do not ask them to strip their only starter.
            if pos in STREAM_POS and depth < 2:
                continue

            delta = None if ours is None else round(ours - their_rank, 1)
            offer = _surplus_offer(
                team_name, other, pos, grades_by_team, rosters, players, rank_index
            )

            need_label = "Weak" if pos in weak_pos else "Average"
            if ours is None:
                why = (
                    f"You need {pos} ({need_label}, no ranked starter); "
                    f"{player.name} is consensus #{int(their_rank)} "
                    f"on {other} (replacement ~#{int(repl)})."
                )
            else:
                why = (
                    f"Your {pos} grades {need_label} (best: {our_name or '—'} #{int(ours)}); "
                    f"{player.name} is #{int(their_rank)} on {other} "
                    f"(+{int(delta)} rank spots)."
                )
            if pos in STREAM_POS:
                why += (
                    f" Streaming slot — only suggesting because your {pos} is a clear hole "
                    f"and {player.name} is a top-{int(STREAM_ELITE_RANK.get(pos, 8))} upgrade."
                )
            if depth >= 2:
                why += f" {other} has {depth} {pos}s — surplus makes them likelier to deal."
            else:
                why += f" {other} is thin at {pos} ({depth}); may want overpay."
            if offer:
                why += f" {offer}."

            # Score: skill upgrades first; bigger delta; surplus counterpart.
            upgrade = (ours - their_rank) if ours is not None else (repl - their_rank + 10)
            score = float(upgrade)
            if pos in CORE_POS_SET:
                score += 30.0
                if pos in weak_pos:
                    score += 12.0
                # Earlier in need_pos = higher priority (Weak before Average).
                score += max(0, 6 - need_pos.index(pos)) * 1.5
            else:
                # Stream trades are last-resort noise unless elite.
                score -= 20.0
            if depth >= 2:
                score += 5.0 if pos in CORE_POS_SET else 3.0
            if offer:
                score += 2.0

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

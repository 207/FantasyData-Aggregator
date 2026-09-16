from __future__ import annotations

"""Find trade targets on other rosters that fill hunt positions + their needs."""

from typing import Any, Iterable, Sequence

from analysis.roster_grader import REPLACEMENT_RANK, grade_roster
from ingestion.consensus import index_rankings_by_name, normalize_player_name
from ingestion.positions import normalize_position

SKILL_POS = {"QB", "RB", "WR", "TE", "DST", "K"}
ALL_HUNT_POS = ("QB", "RB", "WR", "TE", "DST", "K")

# Positions worth trading for in most leagues (starters + FLEX) — UI default.
CORE_POS = ("RB", "WR", "TE")
CORE_POS_SET = frozenset(CORE_POS)

# Streamable / scarce slots — usually fixed on waivers, not trades.
STREAM_POS = frozenset({"QB", "DST", "K"})

# Target must clear this rank to be a trade-worthy stream upgrade (not a lateral).
STREAM_ELITE_RANK = {"QB": 6, "DST": 5, "K": 4}

# Absolute "this is a real hole" floor in a 12-team league.
# Purdy-tier QB14 is startable — never a trade need. Only chase when missing / QB18+.
STREAM_HOLE_RANK = {"QB": 18, "DST": 16, "K": 16}

# Minimum rank-spot gain to bother trading for a stream position.
STREAM_MIN_DELTA = 6


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
    """True when QB/DST/K is a real hole — not a startable mid-tier like Purdy QB14."""
    pos = grade.get("position")
    if pos not in STREAM_POS:
        return False
    hole_at = float(STREAM_HOLE_RANK.get(pos, 18))
    best = grade.get("best_rank")
    if best is None:
        # Empty / unranked — only count as a hole when the grader already says Weak.
        return grade.get("grade") == "Weak" or int(grade.get("count") or 0) == 0
    try:
        return float(best) > hole_at
    except (TypeError, ValueError):
        return grade.get("grade") == "Weak"


def _normalize_hunt_positions(hunt_positions: Sequence[str] | None) -> list[str]:
    """Dedupe + order hunt positions; default RB/WR/TE (all skill)."""
    if not hunt_positions:
        return list(CORE_POS)
    seen: set[str] = set()
    out: list[str] = []
    for raw in hunt_positions:
        pos = normalize_position(raw or "")
        if pos not in SKILL_POS or pos in seen:
            continue
        seen.add(pos)
        out.append(pos)
    return out or list(CORE_POS)


def _trade_need_positions(grades: list[dict[str, Any]]) -> list[str]:
    """
    Auto fallback when UI doesn't pass hunt positions.

    Prefer RB/WR/TE (Weak then Average — covers FLEX depth). Only add QB/DST/K
    when that slot is a clear hole; never let mild DST/QB Weak drown out skill needs.
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

    # Stacked core — last resort: Average skill only (never default to QB/DST/K).
    return [
        g["position"]
        for g in grades
        if g.get("grade") == "Average" and g.get("position") in CORE_POS_SET
    ]


def _stream_target_ok(
    pos: str,
    their_rank: float,
    ours: float | None,
    *,
    explicit_hunt: bool,
) -> bool:
    """Filter streaming-slot targets to meaningful upgrades only."""
    elite = float(STREAM_ELITE_RANK.get(pos, 8))
    if explicit_hunt:
        # User explicitly asked for this slot — allow any real upgrade, not only elite.
        if ours is None:
            return their_rank <= elite * 2
        if their_rank >= ours:
            return False
        return (ours - their_rank) >= max(3.0, STREAM_MIN_DELTA / 2)
    if their_rank > elite:
        return False
    if ours is None:
        return their_rank <= elite
    if their_rank >= ours:
        return False
    return (ours - their_rank) >= STREAM_MIN_DELTA


def _surplus_positions(my_grades: dict[str, dict]) -> list[str]:
    """Positions where we grade Strong (offerable surplus). Prefer skill."""
    strong = [pos for pos, g in my_grades.items() if g.get("grade") == "Strong"]
    strong.sort(key=lambda p: (0 if p in CORE_POS_SET else 1, ALL_HUNT_POS.index(p) if p in ALL_HUNT_POS else 99))
    return strong


def _counterparty_need_fit(
    their_grades: dict[str, dict],
    my_surplus: Iterable[str],
) -> tuple[float, list[str]]:
    """
    Score how well our surplus fills *their* holes.

    Weak need + our Strong surplus is the primary matchmaking signal.
    """
    surplus = set(my_surplus)
    hits: list[str] = []
    score = 0.0
    for pos in surplus:
        their = their_grades.get(pos)
        if not their:
            continue
        grade = their.get("grade")
        if grade == "Weak" or (pos in STREAM_POS and _is_stream_hole(their)):
            score += 18.0 if pos in CORE_POS_SET else 10.0
            hits.append(pos)
        elif grade == "Average":
            score += 8.0 if pos in CORE_POS_SET else 3.0
            hits.append(pos)
    return score, hits


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
        # Prefer filling their Weak over Average.
        their_grade = their.get("grade", "Weak")
        need_penalty = 0.0 if their_grade == "Weak" else 8.0
        core_penalty = 0.0 if pos in CORE_POS_SET else 50.0
        candidates.append((need_penalty + core_penalty, offer_rank, offer_name, pos))

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
    hunt_positions: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Surface players on other teams at selected hunt positions.

    Strategy (user-driven hunt + counterparty-first matchmaking):
    - Hunt upgrades at `hunt_positions` (default RB/WR/TE) even if you grade
      Strong there — you can still climb the board.
    - Prefer counterparties who are Weak/Average at positions where *you* have
      Strong surplus, so the offer fills *their* hole.
    - Auto mode (no hunt_positions) still falls back to skill-first needs.
    """
    rank_index = index_rankings_by_name(consensus_rankings or [])
    my_grades_list = grade_roster(team_name, rosters, players, consensus_rankings)
    my_grades = {g["position"]: g for g in my_grades_list}
    weak_pos = {g["position"] for g in my_grades_list if g["grade"] == "Weak"}
    average_pos = {g["position"] for g in my_grades_list if g["grade"] == "Average"}

    explicit = hunt_positions is not None
    if explicit:
        need_pos = _normalize_hunt_positions(hunt_positions)
    else:
        need_pos = _trade_need_positions(my_grades_list)
    if not need_pos:
        return []

    team_names = sorted({r.team_name for r in rosters})
    grades_by_team = {
        t: grade_roster(t, rosters, players, consensus_rankings) for t in team_names
    }
    my_surplus = _surplus_positions(my_grades)

    my_best: dict[str, tuple[float | None, str | None]] = {
        pos: _best_rank_at_pos(team_name, pos, rosters, players, rank_index) for pos in need_pos
    }

    # Precompute counterparty fit once per owner.
    fit_by_owner: dict[str, tuple[float, list[str]]] = {}
    for other in team_names:
        if other == team_name:
            continue
        their_map = {g["position"]: g for g in grades_by_team.get(other, [])}
        fit_by_owner[other] = _counterparty_need_fit(their_map, my_surplus)

    scored: list[dict[str, Any]] = []
    seen: set[str] = set()

    for other in team_names:
        if other == team_name:
            continue
        fit_score, fit_positions = fit_by_owner.get(other, (0.0, []))
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

            if pos in STREAM_POS and not _stream_target_ok(
                pos, their_rank, ours, explicit_hunt=explicit and pos in need_pos
            ):
                continue

            depth = _pos_depth(other, pos, rosters, players)
            # Prefer trading from their surplus; for stream slots require depth
            # unless the user explicitly hunted that stream position.
            if pos in STREAM_POS and depth < 2 and not (explicit and pos in need_pos):
                continue

            delta = None if ours is None else round(ours - their_rank, 1)
            offer = _surplus_offer(
                team_name, other, pos, grades_by_team, rosters, players, rank_index
            )

            your_grade = my_grades.get(pos, {}).get("grade", "—")
            if pos in weak_pos:
                need_label = "Weak"
            elif pos in average_pos:
                need_label = "Average"
            else:
                need_label = your_grade or "Strong"

            if explicit:
                hunt_lead = f"Hunting {pos} (you selected"
                if need_label == "Strong":
                    hunt_lead += "; your roster already grades Strong — still shopping upgrades"
                else:
                    hunt_lead += f"; your {pos} grades {need_label}"
                hunt_lead += "). "
            else:
                hunt_lead = f"Auto need at {pos} ({need_label}). "

            if ours is None:
                why = (
                    f"{hunt_lead}"
                    f"{player.name} is consensus #{int(their_rank)} "
                    f"on {other} (replacement ~#{int(repl)})."
                )
            else:
                why = (
                    f"{hunt_lead}"
                    f"Your best: {our_name or '—'} #{int(ours)}; "
                    f"{player.name} is #{int(their_rank)} on {other} "
                    f"(+{int(delta)} rank spots)."
                )

            if fit_positions:
                why += (
                    f" {other} needs help at {', '.join(fit_positions)} "
                    f"— positions where you have surplus to offer."
                )
            if pos in STREAM_POS and not explicit:
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

            # Score: counterparty need-fit first, then upgrade quality.
            upgrade = (ours - their_rank) if ours is not None else (repl - their_rank + 10)
            score = float(upgrade) + float(fit_score)
            if offer:
                score += 12.0  # fill-their-hole offer is first-class
            if pos in CORE_POS_SET:
                score += 20.0
                if pos in weak_pos:
                    score += 4.0  # mild — no longer the main driver
                score += max(0, 6 - need_pos.index(pos)) * 1.0
            else:
                if not explicit:
                    score -= 20.0
                else:
                    score -= 5.0
            if depth >= 2:
                score += 5.0 if pos in CORE_POS_SET else 3.0

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
                    "their_needs": ", ".join(fit_positions) if fit_positions else "—",
                    "why": why,
                    "_score": score,
                }
            )
            seen.add(pid)

    scored.sort(key=lambda r: (-r["_score"], r["rank"]))
    for row in scored:
        row.pop("_score", None)
    return scored[:limit]

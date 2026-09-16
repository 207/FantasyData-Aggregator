from __future__ import annotations

from collections import defaultdict
from typing import Any

from ingestion.consensus import index_rankings_by_name, normalize_player_name
from ingestion.positions import normalize_position

POSITION_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "DST", "K"]

# Positional replacement-level ranks (approx starter cutoff in 12-team).
REPLACEMENT_RANK = {
    "QB": 12,
    "RB": 24,
    "WR": 36,
    "TE": 12,
    "DST": 12,
    "K": 12,
}


def _player_pos(player: Any, row: Any) -> str:
    pos = normalize_position(getattr(player, "position", None) or "")
    if pos and pos not in {"BE", "IR", "FLEX"}:
        return pos
    return normalize_position(getattr(row, "lineup_slot", None) or "") or "?"


def grade_roster(
    team_name: str,
    rosters: list[Any],
    players: dict[str, Any],
    consensus_rankings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Positional strength grades.

    When consensus rankings are available, grades use best starter rank vs
    replacement level. Otherwise falls back to Phase-1 depth-only scoring.
    """
    by_pos: dict[str, list[Any]] = defaultdict(list)
    team_rows = [r for r in rosters if r.team_name == team_name]
    for row in team_rows:
        player = players.get(row.player_id)
        if not player:
            continue
        pos = _player_pos(player, row)
        if pos in {"?", "BE", "IR", "FLEX"}:
            continue
        by_pos[pos].append(player)

    rank_index = index_rankings_by_name(consensus_rankings or [])
    use_ranks = bool(rank_index)

    grades: list[dict[str, Any]] = []
    for pos in POSITION_ORDER:
        if pos == "FLEX":
            continue
        names_players = by_pos.get(pos, [])
        count = len(names_players)
        names = [p.name for p in names_players]

        if use_ranks and count:
            ranked: list[tuple[float, str]] = []
            for p in names_players:
                key = (normalize_player_name(p.name, pos), pos)
                hit = rank_index.get(key)
                if hit:
                    ranked.append((float(hit.get("rank") or hit.get("avg_rank") or 999), p.name))
                else:
                    ranked.append((999.0, p.name))
            ranked.sort(key=lambda t: t[0])
            best_rank, best_name = ranked[0]
            repl = REPLACEMENT_RANK.get(pos, 24)
            starters_above = sum(1 for r, _ in ranked if r <= repl)

            if best_rank <= repl * 0.5:
                grade = "Strong"
            elif best_rank <= repl:
                grade = "Average"
            else:
                grade = "Weak"

            if best_rank >= 900:
                why = (
                    f"{count} {pos}(s) on roster but no consensus rank match — "
                    f"depth-only signal."
                )
                # soften unknown ranks toward depth logic
                if pos in {"QB", "TE", "DST", "K"}:
                    grade = "Average" if count == 1 else ("Strong" if count >= 2 else "Weak")
                else:
                    grade = "Strong" if count >= 3 else ("Average" if count == 2 else "Weak")
            else:
                why = (
                    f"Best {pos}: {best_name} consensus #{int(best_rank)} "
                    f"(replacement ~#{repl}); {starters_above} at/above replacement."
                )
        else:
            # Depth-only fallback
            if pos in {"QB", "TE", "DST", "K"}:
                if count >= 2:
                    grade, why = "Strong", f"{count} players at {pos} — depth for bye weeks."
                elif count == 1:
                    grade, why = "Average", f"Single {pos}; streaming risk on bye/injury."
                else:
                    grade, why = "Weak", f"No {pos} on roster."
            else:  # RB / WR
                if count >= 3:
                    grade, why = "Strong", f"{count} {pos}s — surplus for flex/trades."
                elif count == 2:
                    grade, why = "Average", f"Two {pos}s fills starters; thin behind them."
                elif count == 1:
                    grade, why = "Weak", f"Only one {pos}; vulnerable if starter sits."
                else:
                    grade, why = "Weak", f"No {pos} depth."

            best_rank = None

        grades.append(
            {
                "position": pos,
                "grade": grade,
                "count": count,
                "players": ", ".join(names) if names else "—",
                "best_rank": None if not use_ranks else (None if count == 0 else (int(best_rank) if best_rank < 900 else None)),
                "why": why if count or not use_ranks else f"No {pos} on roster.",
            }
        )
        if count == 0:
            grades[-1]["grade"] = "Weak"
            grades[-1]["why"] = f"No {pos} on roster."
            grades[-1]["best_rank"] = None
    return grades


def position_counts_for_team(team_name: str, rosters: list[Any], players: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rosters:
        if row.team_name != team_name:
            continue
        player = players.get(row.player_id)
        if player:
            pos = normalize_position(player.position)
            if pos:
                counts[pos] += 1
    return dict(counts)

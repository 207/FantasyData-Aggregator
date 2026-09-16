from __future__ import annotations

from collections import defaultdict
from typing import Any


POSITION_ORDER = ["QB", "RB", "WR", "TE", "FLEX", "DST", "K"]


def grade_roster(
    team_name: str,
    rosters: list[Any],
    players: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Phase-1 positional strength snapshot based on roster depth only.

    Later phases replace this with consensus rankings vs replacement level.
    """
    by_pos: dict[str, list[str]] = defaultdict(list)
    team_rows = [r for r in rosters if r.team_name == team_name]
    for row in team_rows:
        player = players.get(row.player_id)
        if not player:
            continue
        pos = player.position or row.lineup_slot or "?"
        by_pos[pos].append(player.name)

    grades: list[dict[str, Any]] = []
    for pos in POSITION_ORDER:
        names = by_pos.get(pos, [])
        count = len(names)
        if pos in {"QB", "TE", "DST", "K"}:
            if count >= 2:
                grade, why = "Strong", f"{count} players at {pos} — depth for bye weeks."
            elif count == 1:
                grade, why = "Average", f"Single {pos}; streaming risk on bye/injury."
            else:
                grade, why = "Weak", f"No {pos} on roster."
        elif pos == "FLEX":
            continue
        else:  # RB / WR
            if count >= 3:
                grade, why = "Strong", f"{count} {pos}s — surplus for flex/trades."
            elif count == 2:
                grade, why = "Average", f"Two {pos}s fills starters; thin behind them."
            elif count == 1:
                grade, why = "Weak", f"Only one {pos}; vulnerable if starter sits."
            else:
                grade, why = "Weak", f"No {pos} depth."

        grades.append(
            {
                "position": pos,
                "grade": grade,
                "count": count,
                "players": ", ".join(names) if names else "—",
                "why": why,
            }
        )
    return grades


def position_counts_for_team(team_name: str, rosters: list[Any], players: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rosters:
        if row.team_name != team_name:
            continue
        player = players.get(row.player_id)
        if player:
            counts[player.position] += 1
    return dict(counts)

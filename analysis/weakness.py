from __future__ import annotations

"""Basic positional weakness flags from ROS depth vs starter slots."""

from collections import defaultdict
from typing import Any

from ingestion.consensus import index_rankings_by_name, normalize_player_name
from ingestion.positions import normalize_position

# Default ESPN-style starter counts when league slots are missing.
DEFAULT_STARTER_SLOTS = {
    "QB": 1,
    "RB": 2,
    "WR": 2,
    "TE": 1,
    "FLEX": 1,
    "DST": 1,
    "K": 1,
}

SKILL_FOR_FLEX = frozenset({"RB", "WR", "TE"})
TRADE_POS = frozenset({"RB", "WR", "TE"})  # Never flag QB/DST/K as trade weakness targets


def parse_starter_slots(roster_slots: dict[str, Any] | str | None) -> dict[str, int]:
    """Normalize ESPN position_slot_counts into starter counts (bench/IR ignored)."""
    import json

    raw = roster_slots
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) or {}
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict) or not raw:
        return dict(DEFAULT_STARTER_SLOTS)

    out = dict(DEFAULT_STARTER_SLOTS)
    # ESPN keys vary: "QB", "RB", "WR", "TE", "FLEX", "D/ST", "K", "BE", "IR"
    key_map = {
        "QB": "QB",
        "RB": "RB",
        "WR": "WR",
        "TE": "TE",
        "FLEX": "FLEX",
        "DST": "DST",
        "D/ST": "DST",
        "DEF": "DST",
        "K": "K",
    }
    for key, count in raw.items():
        pos = key_map.get(str(key).upper()) or key_map.get(normalize_position(str(key)))
        if not pos:
            continue
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out[pos] = n
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


def team_depth_chart(
    team_name: str,
    rosters: list[Any],
    players: dict[str, Any],
    ros_rankings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Ordered depth chart per position using ROS ranks (missing ranks sort last)."""
    rank_index = index_rankings_by_name(ros_rankings)
    by_pos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rosters:
        if row.team_name != team_name:
            continue
        player = players.get(row.player_id)
        if not player:
            continue
        pos = normalize_position(getattr(player, "position", "") or "")
        if pos not in {"QB", "RB", "WR", "TE", "DST", "K"}:
            continue
        rank = _rank_for(player, rank_index)
        by_pos[pos].append(
            {
                "player_id": str(row.player_id),
                "name": player.name,
                "position": pos,
                "rank": rank,
                "slot": getattr(row, "slot", "bench"),
            }
        )
    for pos, items in by_pos.items():
        items.sort(key=lambda x: (x["rank"] is None, x["rank"] if x["rank"] is not None else 999))
    return dict(by_pos)


def weakness_flags_for_team(
    team_name: str,
    rosters: list[Any],
    players: dict[str, Any],
    ros_rankings: list[dict[str, Any]],
    roster_slots: dict[str, Any] | str | None = None,
) -> list[dict[str, Any]]:
    """
    Simple weakness flags: compare ROS-ranked depth to starter slot counts.

    A position is Weak when starter slots aren't filled by players at/near
    replacement, or depth count is below starter need. FLEX uses leftover RB/WR/TE.
    """
    slots = parse_starter_slots(roster_slots)
    depth = team_depth_chart(team_name, rosters, players, ros_rankings)
    # Replacement-ish cutoffs for "startable" (12-team)
    startable = {"QB": 15, "RB": 30, "WR": 40, "TE": 14, "DST": 14, "K": 14}

    flags: list[dict[str, Any]] = []
    for pos in ("QB", "RB", "WR", "TE", "DST", "K"):
        need = int(slots.get(pos, 0) or 0)
        if need <= 0:
            continue
        chart = depth.get(pos) or []
        startable_cut = float(startable.get(pos, 24))
        startable_players = [
            p for p in chart if p["rank"] is not None and p["rank"] <= startable_cut
        ]
        best = chart[0] if chart else None
        best_rank = best["rank"] if best else None
        count = len(chart)
        if count < need:
            level = "Weak"
            why = f"Only {count} {pos}(s) rostered vs {need} starter slot(s)."
        elif len(startable_players) < need:
            level = "Weak"
            why = (
                f"{len(startable_players)} startable {pos}(s) (ROS ≤ {int(startable_cut)}) "
                f"vs {need} starter slot(s); best ROS #{int(best_rank) if best_rank else '—'}."
            )
        elif best_rank is not None and best_rank > startable_cut * 0.75 and pos in TRADE_POS:
            level = "Thin"
            why = f"Best {pos} is ROS #{int(best_rank)} — playable but thin for upgrades."
        else:
            level = "OK"
            why = (
                f"{count} rostered, {len(startable_players)} startable; "
                f"best ROS #{int(best_rank) if best_rank else '—'}."
            )
        flags.append(
            {
                "team": team_name,
                "position": pos,
                "level": level,
                "starter_slots": need,
                "rostered": count,
                "startable": len(startable_players),
                "best_rank": best_rank,
                "best_player": best["name"] if best else None,
                "trade_relevant": pos in TRADE_POS and level in {"Weak", "Thin"},
                "why": why,
            }
        )

    # FLEX: need leftover RB/WR/TE after filling primary slots
    flex_need = int(slots.get("FLEX", 0) or 0)
    if flex_need > 0:
        leftovers: list[dict[str, Any]] = []
        for pos in ("RB", "WR", "TE"):
            primary = int(slots.get(pos, 0) or 0)
            chart = depth.get(pos) or []
            leftovers.extend(chart[primary:])
        leftovers.sort(key=lambda x: (x["rank"] is None, x["rank"] if x["rank"] is not None else 999))
        flex_startable = [
            p
            for p in leftovers
            if p["rank"] is not None and p["rank"] <= float(startable.get(p["position"], 36))
        ]
        if len(flex_startable) < flex_need:
            level = "Weak"
            why = f"Only {len(flex_startable)} leftover skill player(s) for {flex_need} FLEX slot(s)."
        else:
            level = "OK"
            why = f"{len(flex_startable)} leftover skill options for {flex_need} FLEX."
        flags.append(
            {
                "team": team_name,
                "position": "FLEX",
                "level": level,
                "starter_slots": flex_need,
                "rostered": len(leftovers),
                "startable": len(flex_startable),
                "best_rank": leftovers[0]["rank"] if leftovers else None,
                "best_player": leftovers[0]["name"] if leftovers else None,
                "trade_relevant": level == "Weak",
                "why": why,
            }
        )
    return flags


def all_team_weakness_flags(
    team_names: list[str],
    rosters: list[Any],
    players: dict[str, Any],
    ros_rankings: list[dict[str, Any]],
    roster_slots: dict[str, Any] | str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for team in team_names:
        out.extend(
            weakness_flags_for_team(team, rosters, players, ros_rankings, roster_slots)
        )
    return out

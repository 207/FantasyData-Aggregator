from __future__ import annotations

"""ESPN projected-points rankings — third low-effort source when league is live."""

from datetime import datetime, timezone
from typing import Any

from ingestion.positions import normalize_position


def rankings_from_espn_players(
    players: list[dict[str, Any]],
    *,
    week: int,
    horizon: str,
) -> list[dict[str, Any]]:
    """
    Build positional ranks from ESPN projected points when present on player dicts.

    Demo / FA payloads may include projected_points; otherwise returns [].
    """
    by_pos: dict[str, list[tuple[float, dict]]] = {}
    for p in players:
        pos = normalize_position(p.get("position") or "")
        if pos not in {"QB", "RB", "WR", "TE", "DST", "K"}:
            continue
        pts = p.get("projected_points")
        if pts is None:
            pts = p.get("proj")
        try:
            pts_f = float(pts)
        except (TypeError, ValueError):
            continue
        if pts_f <= 0:
            continue
        by_pos.setdefault(pos, []).append((pts_f, p))

    pulled = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for pos, items in by_pos.items():
        items.sort(key=lambda t: t[0], reverse=True)
        for i, (pts, p) in enumerate(items, start=1):
            out.append(
                {
                    "name": p.get("name"),
                    "position": pos,
                    "rank": i,
                    "tier": (i - 1) // 6 + 1,
                    "projected_points": pts,
                    "source": "espn",
                    "horizon": horizon,
                    "week": week,
                    "pulled_at": pulled,
                    "player_id": str(p.get("player_id") or ""),
                }
            )
    return out


def try_enrich_espn_projections(league: Any, players: dict[str, dict]) -> None:
    """Best-effort: copy projected points from espn_api player objects onto our map."""
    # Called from espn_adapter when live; no-op if attrs missing.
    for team in getattr(league, "teams", []) or []:
        for player in getattr(team, "roster", []) or []:
            pid = str(getattr(player, "playerId", None) or getattr(player, "id", "") or "")
            if not pid or pid not in players:
                continue
            proj = getattr(player, "projected_total_points", None)
            if proj is None:
                proj = getattr(player, "projected_avg_points", None)
            if proj is None:
                proj = getattr(player, "projected_points", None)
            try:
                players[pid]["projected_points"] = float(proj)
            except (TypeError, ValueError):
                pass

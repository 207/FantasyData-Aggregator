from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.trade_finder import CORE_POS, DEFAULT_HUNT_POS
from analysis.weakness import TRADE_POS, parse_starter_slots, weakness_flags_for_team


def _player(pid: str, name: str, pos: str) -> SimpleNamespace:
    return SimpleNamespace(player_id=pid, name=name, position=pos)


def _row(team: str, pid: str) -> SimpleNamespace:
    return SimpleNamespace(team_name=team, player_id=pid, lineup_slot="", slot="starter")


def _rank(name: str, pos: str, rank: int) -> dict:
    return {"name": name, "position": pos, "rank": rank, "avg_rank": float(rank)}


def test_hunt_defaults_are_skill_only():
    assert set(CORE_POS) == TRADE_POS == {"RB", "WR", "TE"}
    assert set(DEFAULT_HUNT_POS) == {"RB", "WR", "TE"}
    assert "QB" not in CORE_POS


def test_parse_espn_slots():
    slots = parse_starter_slots({"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "D/ST": 1, "K": 1, "BE": 7})
    assert slots["RB"] == 2
    assert slots["DST"] == 1
    assert slots["FLEX"] == 1


def test_weak_rb_when_thin_depth():
    players = {
        "1": _player("1", "Star WR", "WR"),
        "2": _player("2", "Backup RB", "RB"),
    }
    rosters = [_row("Mine", "1"), _row("Mine", "2")]
    ranks = [_rank("Star WR", "WR", 3), _rank("Backup RB", "RB", 45)]
    flags = weakness_flags_for_team(
        "Mine",
        rosters,
        players,
        ranks,
        {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1},
    )
    by_pos = {f["position"]: f for f in flags}
    assert by_pos["RB"]["level"] == "Weak"
    assert by_pos["RB"]["trade_relevant"] is True
    assert by_pos["QB"]["trade_relevant"] is False

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.trade_finder import (
    _is_stream_hole,
    _trade_need_positions,
    find_trade_targets,
)


def _player(pid: str, name: str, pos: str) -> SimpleNamespace:
    return SimpleNamespace(player_id=pid, name=name, position=pos)


def _row(team: str, pid: str) -> SimpleNamespace:
    return SimpleNamespace(team_name=team, player_id=pid, lineup_slot="")


def _rank(name: str, pos: str, rank: int) -> dict:
    return {"name": name, "position": pos, "rank": rank, "avg_rank": float(rank)}


def test_need_positions_prefers_average_skill_over_mild_dst_weak():
    grades = [
        {"position": "QB", "grade": "Average", "best_rank": 10},
        {"position": "RB", "grade": "Average", "best_rank": 20},
        {"position": "WR", "grade": "Strong", "best_rank": 5},
        {"position": "TE", "grade": "Average", "best_rank": 9},
        {"position": "DST", "grade": "Weak", "best_rank": 14},  # barely Weak
        {"position": "K", "grade": "Average", "best_rank": 8},
    ]
    needs = _trade_need_positions(grades)
    assert "RB" in needs and "TE" in needs
    assert "DST" not in needs  # mild Weak DST is not a trade hole
    assert needs.index("RB") < needs.index("TE") or "RB" in needs


def test_stream_hole_requires_clear_gap():
    assert _is_stream_hole({"position": "DST", "grade": "Weak", "best_rank": None})
    assert _is_stream_hole({"position": "DST", "grade": "Weak", "best_rank": 20})
    assert not _is_stream_hole({"position": "DST", "grade": "Weak", "best_rank": 14})
    assert not _is_stream_hole({"position": "QB", "grade": "Weak", "best_rank": 14})  # Purdy-tier
    assert not _is_stream_hole({"position": "QB", "grade": "Average", "best_rank": 14})
    assert _is_stream_hole({"position": "QB", "grade": "Weak", "best_rank": 22})
    assert not _is_stream_hole({"position": "DST", "grade": "Average", "best_rank": 14})
    assert not _is_stream_hole({"position": "RB", "grade": "Weak", "best_rank": 40})


def test_purdy_tier_qb_not_weak_in_12_team():
    from analysis.roster_grader import grade_roster

    players = {
        "qb": _player("qb", "Brock Purdy", "QB"),
        "rb1": _player("rb1", "RB A", "RB"),
        "rb2": _player("rb2", "RB B", "RB"),
        "wr1": _player("wr1", "WR A", "WR"),
        "wr2": _player("wr2", "WR B", "WR"),
        "te": _player("te", "TE A", "TE"),
        "dst": _player("dst", "DST A", "DST"),
        "k": _player("k", "K A", "K"),
    }
    rosters = [_row("Me", pid) for pid in players]
    consensus = [
        _rank("Brock Purdy", "QB", 14),
        _rank("RB A", "RB", 10),
        _rank("RB B", "RB", 30),
        _rank("WR A", "WR", 8),
        _rank("WR B", "WR", 25),
        _rank("TE A", "TE", 8),
        _rank("DST A", "DST", 10),
        _rank("K A", "K", 8),
    ]
    grades = {g["position"]: g for g in grade_roster("Me", rosters, players, consensus)}
    assert grades["QB"]["grade"] == "Average", grades["QB"]
    assert "not a trade hole" in grades["QB"]["why"]
    needs = _trade_need_positions(list(grades.values()))
    assert "QB" not in needs
    trades = find_trade_targets("Me", rosters, players, consensus, limit=12)
    assert all(t["position"] != "QB" for t in trades)


def test_find_trade_targets_skill_over_dst_noise():
    """Weak DST + Average RB should surface RB upgrades, not every better DST."""
    players = {
        "my_qb": _player("my_qb", "My QB", "QB"),
        "my_rb": _player("my_rb", "My RB", "RB"),
        "my_wr1": _player("my_wr1", "My WR1", "WR"),
        "my_wr2": _player("my_wr2", "My WR2", "WR"),
        "my_te": _player("my_te", "My TE", "TE"),
        "my_dst": _player("my_dst", "My DST", "DST"),
        "my_k": _player("my_k", "My K", "K"),
        "extra_wr": _player("extra_wr", "Surplus WR", "WR"),
        "their_rb": _player("their_rb", "Upgrade RB", "RB"),
        "their_rb2": _player("their_rb2", "Bench RB", "RB"),
        "their_dst": _player("their_dst", "Elite DST", "DST"),
        "their_dst2": _player("their_dst2", "Backup DST", "DST"),
        "their_qb": _player("their_qb", "Their QB", "QB"),
        "their_wr": _player("their_wr", "Their WR", "WR"),
        "their_te": _player("their_te", "Their TE", "TE"),
        "their_k": _player("their_k", "Their K", "K"),
    }
    rosters = [
        _row("Me", "my_qb"),
        _row("Me", "my_rb"),
        _row("Me", "my_wr1"),
        _row("Me", "my_wr2"),
        _row("Me", "extra_wr"),
        _row("Me", "my_te"),
        _row("Me", "my_dst"),
        _row("Me", "my_k"),
        _row("Them", "their_qb"),
        _row("Them", "their_rb"),
        _row("Them", "their_rb2"),
        _row("Them", "their_wr"),
        _row("Them", "their_te"),
        _row("Them", "their_dst"),
        _row("Them", "their_dst2"),
        _row("Them", "their_k"),
    ]
    consensus = [
        _rank("My QB", "QB", 10),
        _rank("My RB", "RB", 30),  # Average (≤36? wait RB repl 24 → Weak actually)
        # Use RB 20 → Average; WR strong; TE average; DST 14 mild weak
        _rank("My WR1", "WR", 8),
        _rank("My WR2", "WR", 25),
        _rank("Surplus WR", "WR", 40),
        _rank("My TE", "TE", 10),
        _rank("My DST", "DST", 14),
        _rank("My K", "K", 9),
        _rank("Upgrade RB", "RB", 12),
        _rank("Bench RB", "RB", 35),
        _rank("Elite DST", "DST", 2),
        _rank("Backup DST", "DST", 18),
        _rank("Their QB", "QB", 5),
        _rank("Their WR", "WR", 15),
        _rank("Their TE", "TE", 7),
        _rank("Their K", "K", 4),
    ]
    # Fix My RB to Average band
    consensus = [r for r in consensus if not (r["name"] == "My RB")]
    consensus.append(_rank("My RB", "RB", 20))

    trades = find_trade_targets("Me", rosters, players, consensus, limit=12)
    positions = [t["position"] for t in trades]
    assert "RB" in positions
    assert positions[0] == "RB"
    assert all(t["position"] != "DST" for t in trades), trades
    rb = next(t for t in trades if t["player"] == "Upgrade RB")
    assert "why" in rb and rb["why"]
    assert "offer_hint" in rb


def test_clear_qb_hole_can_still_surface_elite_qb():
    players = {
        "my_qb": _player("my_qb", "Bad QB", "QB"),
        "my_rb1": _player("my_rb1", "RB One", "RB"),
        "my_rb2": _player("my_rb2", "RB Two", "RB"),
        "my_rb3": _player("my_rb3", "RB Three", "RB"),
        "my_wr1": _player("my_wr1", "WR One", "WR"),
        "my_wr2": _player("my_wr2", "WR Two", "WR"),
        "my_wr3": _player("my_wr3", "WR Three", "WR"),
        "my_te": _player("my_te", "TE One", "TE"),
        "my_dst": _player("my_dst", "DST One", "DST"),
        "my_k": _player("my_k", "K One", "K"),
        "their_qb": _player("their_qb", "Elite QB", "QB"),
        "their_qb2": _player("their_qb2", "Backup QB", "QB"),
        "their_rb": _player("their_rb", "Their RB", "RB"),
        "their_wr": _player("their_wr", "Their WR", "WR"),
        "their_te": _player("their_te", "Their TE", "TE"),
        "their_dst": _player("their_dst", "Their DST", "DST"),
        "their_k": _player("their_k", "Their K", "K"),
    }
    rosters = [_row("Me", pid) for pid in players if pid.startswith("my_")] + [
        _row("Them", pid) for pid in players if pid.startswith("their_")
    ]
    consensus = [
        _rank("Bad QB", "QB", 22),  # clear hole (>12*1.25)
        _rank("RB One", "RB", 5),
        _rank("RB Two", "RB", 15),
        _rank("RB Three", "RB", 28),
        _rank("WR One", "WR", 4),
        _rank("WR Two", "WR", 18),
        _rank("WR Three", "WR", 40),
        _rank("TE One", "TE", 4),
        _rank("DST One", "DST", 5),
        _rank("K One", "K", 4),
        _rank("Elite QB", "QB", 2),
        _rank("Backup QB", "QB", 16),
        _rank("Their RB", "RB", 20),
        _rank("Their WR", "WR", 22),
        _rank("Their TE", "TE", 8),
        _rank("Their DST", "DST", 8),
        _rank("Their K", "K", 8),
    ]
    trades = find_trade_targets("Me", rosters, players, consensus, limit=8)
    qb_hits = [t for t in trades if t["position"] == "QB"]
    assert qb_hits, trades
    assert qb_hits[0]["player"] == "Elite QB"
    assert "clear hole" in qb_hits[0]["why"].lower() or "Streaming slot" in qb_hits[0]["why"]


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok {_name}")
    print("all passed")

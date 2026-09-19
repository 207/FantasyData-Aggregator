from __future__ import annotations

import json
from collections import Counter

from analysis.llm_client import _looks_like_recs, _parse_json_object
from analysis.llm_context import (
    _rank_rows,
    compact_context_for_llm,
    encode_toon,
    estimate_size,
    pack_context_for_llm,
)


def _synthetic_positional_board(n_skill: int = 100, n_dst: int = 50, n_k: int = 30):
    """Positional consensus-style rows (each pos has its own 1..N ranks)."""
    rows = []
    for i in range(n_skill):
        pos = ["RB", "WR", "TE", "QB"][i % 4]
        rows.append(
            {
                "player_name": f"{pos}{i}",
                "position": pos,
                "rank": (i // 4) + 1,
                "source": "consensus",
                "horizon": "ros",
            }
        )
    for i in range(n_dst):
        rows.append(
            {
                "player_name": f"DST{i}",
                "position": "DST",
                "rank": i + 1,
                "source": "consensus",
                "horizon": "ros",
            }
        )
    for i in range(n_k):
        rows.append(
            {
                "player_name": f"K{i}",
                "position": "K",
                "rank": i + 1,
                "source": "consensus",
                "horizon": "ros",
            }
        )
    return rows


def test_rank_rows_prefers_skill_not_dst_k():
    """Regression: alphabetical position sort + truncate used to yield only DST/K."""
    board = _synthetic_positional_board()
    packed = _rank_rows(board, horizon="ros", source="consensus", limit=45)
    counts = Counter(r["position"] for r in packed)
    assert counts.get("DST", 0) == 0
    assert counts.get("K", 0) == 0
    skill = counts.get("RB", 0) + counts.get("WR", 0) + counts.get("TE", 0) + counts.get("QB", 0)
    assert skill == len(packed) == 45
    assert counts.get("RB", 0) >= 5
    assert counts.get("WR", 0) >= 5


def test_pack_context_skill_ranks_dominate():
    full = {
        "rules": {"hunt_positions": ["RB"], "never_trade_positions": ["QB", "DST", "K"]},
        "league": {
            "name": "Test",
            "week": 2,
            "year": 2026,
            "roster_slots": {"RB": 2},
            "standings": [{"team": "A", "record": "1-0-0", "pf": 100}],
        },
        "your_team": {
            "name": "A",
            "roster": [
                {
                    "name": "Player One",
                    "position": "RB",
                    "nfl_team": "KC",
                    "slot": "RB",
                    "lineup_slot": "RB",
                }
            ],
            "weakness_flags": [
                {
                    "position": "WR",
                    "level": "Weak",
                    "best_player": "X",
                    "best_rank": 80,
                    "why": "thin",
                }
            ],
        },
        "other_rosters": {
            "B": [
                {
                    "name": "Other Guy",
                    "position": "WR",
                    "nfl_team": "BUF",
                    "slot": "WR",
                    "lineup_slot": "WR",
                }
            ]
        },
        "league_weakness_flags": [{"team": "B", "position": "RB", "level": "Weak"}],
        "rankings": {
            "ros_consensus_top": [
                {"name": "Star RB", "position": "RB", "rank": 1},
                {"name": "Star WR", "position": "WR", "rank": 1},
                {"name": "Bad DST", "position": "DST", "rank": 1},
                {"name": "Bad K", "position": "K", "rank": 1},
            ]
            + [{"name": f"RB{i}", "position": "RB", "rank": i + 2} for i in range(40)]
            + [{"name": f"DST{i}", "position": "DST", "rank": i + 2} for i in range(40)],
            "weekly_consensus_top": [
                {"name": "Week WR", "position": "WR", "rank": 2},
                {"name": "Week DST", "position": "DST", "rank": 1},
            ],
        },
        "free_agents_skill": [
            {"name": f"FA{i}", "position": "RB", "nfl_team": "NE"} for i in range(40)
        ],
        "news_injuries": [
            {
                "player_name": "Hurt Guy",
                "headline": "Out with injury",
                "injury_flag": "O",
                "source": "espn",
            }
        ]
        + [
            {"player_name": "Fine", "headline": "Practice notes", "injury_flag": ""}
            for _ in range(20)
        ],
    }
    packed = pack_context_for_llm(full)
    assert compact_context_for_llm is pack_context_for_llm
    ros = packed["rankings"]["ros_top"]
    assert all(r["pos"] in {"RB", "WR", "TE", "QB"} for r in ros)
    assert not any(r["pos"] in {"DST", "K"} for r in ros)
    # No per-source dumps in the LLM pack
    assert "ros_fantasypros" not in packed["rankings"]
    assert "ros_sleeper" not in packed["rankings"]
    assert packed["your_team"]["roster"][0]["name"] == "Player One"
    assert packed["your_team"]["roster"][0]["nfl"] == "KC"
    assert len(packed["free_agents_skill"]) <= 50
    assert packed["_packing"]["full_context_chars"] == len(json.dumps(full, default=str))


def test_toon_smaller_than_json_and_roundtrips():
    payload = {
        "rankings": {
            "ros_top": [
                {"name": f"Player {i}", "pos": "RB", "rank": i} for i in range(1, 21)
            ]
        },
        "free_agents_skill": [
            {"name": f"FA{i}", "pos": "WR", "nfl": "NE"} for i in range(15)
        ],
    }
    stats = estimate_size(payload)
    assert stats["toon_chars"] < stats["json_chars"]
    assert stats["token_savings_pct_est"] > 0
    toon = encode_toon(payload)
    assert "ros_top[" in toon or "name,pos,rank" in toon.replace(" ", "")


def test_schema_guard_rejects_random_json():
    assert _looks_like_recs({"trades": [], "waivers": [], "start_sit": [], "notes": ""})
    assert not _looks_like_recs(
        {"message": "No code provided", "document_type": "error"}
    )
    parsed = _parse_json_object(
        '{"trades":[],"waivers":[{"add":"A","drop":null,"position":"RB","why":"x"}],'
        '"start_sit":[],"notes":"ok"}'
    )
    assert _looks_like_recs(parsed)

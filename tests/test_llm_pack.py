from __future__ import annotations

import json

from analysis.llm_client import _looks_like_recs, _parse_json_object
from analysis.llm_context import compact_context_for_llm


def test_compact_context_shrinks_and_keeps_core_keys():
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
            "ros_consensus_top": [{"name": "Star", "position": "RB", "rank": 1}] * 60,
            "weekly_consensus_top": [{"name": "Week", "position": "WR", "rank": 2}] * 60,
            "ros_by_source_sample": {"fantasypros": [{"name": "x"}] * 30},
            "weekly_by_source_sample": {"espn": [{"name": "y"}] * 30},
        },
        "free_agents_skill": [{"name": f"FA{i}", "position": "RB", "nfl_team": "NE"} for i in range(40)],
        "news_injuries": [
            {
                "player_name": "Hurt Guy",
                "headline": "Out with injury",
                "injury_flag": "O",
                "source": "espn",
            }
        ]
        + [{"player_name": "Fine", "headline": "Practice notes", "injury_flag": ""} for _ in range(20)],
    }
    packed = compact_context_for_llm(full)
    assert "ros_by_source_sample" not in packed["rankings"]
    assert packed["your_team"]["roster"][0]["n"] == "Player One"
    assert len(packed["free_agents_skill"]) <= 30
    assert len(json.dumps(packed, separators=(",", ":"))) < len(json.dumps(full))
    assert packed["_packing"]["full_context_chars"] == len(json.dumps(full, default=str))


def test_schema_guard_rejects_random_json():
    assert _looks_like_recs({"trades": [], "waivers": [], "start_sit": [], "notes": ""})
    assert not _looks_like_recs(
        {"message": "No code provided", "document_type": "error"}
    )
    parsed = _parse_json_object('{"trades":[],"waivers":[{"add":"A","drop":null,"position":"RB","why":"x"}],"start_sit":[],"notes":"ok"}')
    assert _looks_like_recs(parsed)

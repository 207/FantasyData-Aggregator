from __future__ import annotations

"""Tests for Reciprocal Rank Fusion / mean / median consensus boards."""

from ingestion.consensus import build_consensus, build_consensus_both


def _src(name: str, pos: str, rank: int, source: str, horizon: str = "ros") -> dict:
    return {
        "name": name,
        "position": pos,
        "rank": rank,
        "source": source,
        "horizon": horizon,
    }


def test_rrf_prefers_agreement_near_top():
    """Player A ranked #1 on both boards beats player B who is #1 on one and #20 on another."""
    fp = [
        _src("Alpha RB", "RB", 1, "fantasypros"),
        _src("Beta RB", "RB", 2, "fantasypros"),
    ]
    sl = [
        _src("Alpha RB", "RB", 1, "sleeper"),
        _src("Beta RB", "RB", 20, "sleeper"),
    ]
    board = build_consensus([fp, sl], week=1, horizon="ros", method="rrf")
    rbs = [r for r in board if r["position"] == "RB"]
    assert rbs[0]["name"] == "Alpha RB"
    assert rbs[0]["rank"] == 1
    assert rbs[0]["fusion_method"] == "rrf"
    assert rbs[0]["source"] == "consensus"
    assert rbs[0]["fusion_score"] > rbs[1]["fusion_score"]


def test_mean_and_median_produce_consensus_source():
    fp = [_src("A", "WR", 1, "fantasypros"), _src("B", "WR", 10, "fantasypros")]
    sl = [_src("A", "WR", 3, "sleeper"), _src("B", "WR", 4, "sleeper")]
    mean_board = build_consensus([fp, sl], week=2, horizon="ros", method="mean")
    med_board = build_consensus([fp, sl], week=2, horizon="ros", method="median")
    assert mean_board[0]["source"] == "consensus"
    assert med_board[0]["fusion_method"] == "median"
    assert {r["horizon"] for r in mean_board} == {"ros"}


def test_build_consensus_both_separates_horizons():
    fp = [
        _src("W", "TE", 1, "fantasypros", "weekly"),
        _src("R", "TE", 1, "fantasypros", "ros"),
    ]
    sl = [
        _src("W", "TE", 2, "sleeper", "weekly"),
        _src("R", "TE", 2, "sleeper", "ros"),
    ]
    both = build_consensus_both([fp, sl], week=3, method="rrf")
    assert any(r["horizon"] == "weekly" and r["name"] == "W" for r in both)
    assert any(r["horizon"] == "ros" and r["name"] == "R" for r in both)

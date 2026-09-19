from __future__ import annotations

from analysis.recommendations import _filter_trades
from ingestion.news_adapter import _flag_from_text


def test_filter_trades_drops_qb_and_unknown():
    context = {
        "your_team": {
            "roster": [
                {"name": "Josh Allen", "position": "QB"},
                {"name": "Breece Hall", "position": "RB"},
            ]
        },
        "other_rosters": {
            "Partner": [
                {"name": "CeeDee Lamb", "position": "WR"},
                {"name": "Travis Kelce", "position": "TE"},
            ]
        },
        "free_agents_skill": [],
    }
    trades = [
        {
            "you_get": ["CeeDee Lamb"],
            "you_send": ["Breece Hall"],
            "partner": "Partner",
            "why": "ok skill trade",
        },
        {
            "you_get": ["CeeDee Lamb"],
            "you_send": ["Josh Allen"],
            "partner": "Partner",
            "why": "qb should drop",
        },
        {
            "you_get": ["Made Up Guy"],
            "you_send": ["Breece Hall"],
            "partner": "Partner",
            "why": "unknown should drop",
        },
    ]
    cleaned = _filter_trades(trades, context)
    assert len(cleaned) == 1
    assert cleaned[0]["you_get"] == ["CeeDee Lamb"]
    assert cleaned[0]["you_send"] == ["Breece Hall"]


def test_flag_from_text_word_boundaries():
    assert _flag_from_text("Player ruled out for Sunday") == "OUT"
    assert _flag_from_text("About to return this week") == "NEWS"
    assert _flag_from_text("Without a doubt ready") == "NEWS"
    assert _flag_from_text("Team announces suspension") == "SUSPENDED"
    assert _flag_from_text("Listed as questionable") == "QUESTIONABLE"

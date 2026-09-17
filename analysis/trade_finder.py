from __future__ import annotations

"""Thin helpers retained after gutting the analytical trade finder.

Heavy fairness / package construction was removed. Weakness flags and LLM
context live in analysis.weakness / analysis.llm_context. This module keeps
shared constants for the UI.
"""

from analysis.weakness import TRADE_POS

# Positions the UI may hunt (skill only — never QB/DST/K trades).
CORE_POS = tuple(sorted(TRADE_POS, key=lambda p: ("RB", "WR", "TE").index(p) if p in {"RB", "WR", "TE"} else 9))
HUNT_POS_OPTIONS = CORE_POS
DEFAULT_HUNT_POS = CORE_POS

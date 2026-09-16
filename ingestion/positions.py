from __future__ import annotations

"""Normalize ESPN / FantasyPros / Sleeper position labels to a shared vocabulary."""

POSITION_ALIASES = {
    "D/ST": "DST",
    "DEF": "DST",
    "D": "DST",
    "DST": "DST",
    "PK": "K",
    "KICKER": "K",
}

# ESPN sometimes returns composite flex slot labels as slot_position strings.
FLEX_SLOT_LABELS = {"RB/WR/TE", "WR/TE", "RB/WR", "FLEX", "OP"}


def normalize_position(pos: str | None) -> str:
    raw = (pos or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper in POSITION_ALIASES:
        return POSITION_ALIASES[upper]
    # Preserve canonical fantasy positions
    if upper in {"QB", "RB", "WR", "TE", "K", "DST", "FLEX", "BE", "IR"}:
        return upper if upper != "DST" else "DST"
    return POSITION_ALIASES.get(raw, raw)


def normalize_lineup_slot(slot: str | int | None, position: str = "") -> tuple[str, str]:
    """
    Return (slot_category, lineup_label).

    slot_category: starter | bench | IR
    lineup_label: QB, RB, WR, TE, FLEX, DST, K, BE, IR, …
    """
    mapping = {
        0: ("starter", "QB"),
        2: ("starter", "RB"),
        4: ("starter", "WR"),
        6: ("starter", "TE"),
        16: ("starter", "DST"),
        17: ("starter", "K"),
        20: ("bench", "BE"),
        21: ("IR", "IR"),
        23: ("starter", "FLEX"),
    }
    if isinstance(slot, int) or (isinstance(slot, str) and slot.isdigit()):
        sid = int(slot)
        if sid in mapping:
            return mapping[sid]
        pos = normalize_position(position) or "BE"
        return ("bench", pos)

    if isinstance(slot, str):
        label = slot.strip()
        if label in FLEX_SLOT_LABELS:
            return ("starter", "FLEX")
        if label in {"BE", "Bench"}:
            return ("bench", "BE")
        if label == "IR":
            return ("IR", "IR")
        norm = normalize_position(label)
        if norm in {"QB", "RB", "WR", "TE", "DST", "K", "FLEX"}:
            return ("starter", norm)
        return ("bench", norm or label)

    pos = normalize_position(position) or "BE"
    return ("bench", pos)

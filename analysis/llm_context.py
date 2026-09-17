from __future__ import annotations

"""Build structured context for LLM trade / waiver / start-sit recommendations.

Default wire format for Ollama is TOON (Token-Oriented Object Notation) via the
`toon-format` package — tabular arrays cut token use so we can send richer
roster/rank/injury/FA detail than the old compacted JSON pack. Responses are
still JSON for reliable parsing. JSON export remains available for Claude paste.
"""

import json
import os
from typing import Any

from analysis.weakness import TRADE_POS, all_team_weakness_flags, weakness_flags_for_team
from ingestion.positions import normalize_position

NEVER_TRADE_POS = frozenset({"QB", "DST", "K"})
# Positions we want on the rank board for trades/waivers/start-sit.
SKILL_RANK_POS = frozenset({"RB", "WR", "TE", "QB"})
# DST/K sort alphabetically first; including them before truncate wiped skill ranks.
OMIT_RANK_POS = frozenset({"DST", "K", "DEF", "D/ST"})


def context_format() -> str:
    """Wire format for LLM prompts: toon (default) | json."""
    raw = (os.getenv("LLM_CONTEXT_FORMAT", "toon") or "toon").strip().lower()
    return "json" if raw == "json" else "toon"


def _rank_rows(
    rankings: list[Any],
    *,
    horizon: str | None = None,
    source: str | None = None,
    limit: int = 80,
    positions: frozenset[str] | None = SKILL_RANK_POS,
) -> list[dict[str, Any]]:
    """
    Select ranking rows for LLM/export context.

    Consensus boards are *positional* (each pos has ranks 1..N). Sorting by
    position string then truncating preferred DST/K alphabetically and dropped
    RB/WR/TE. We filter to skill positions and sort by rank ascending.
    """
    rows: list[dict[str, Any]] = []
    for r in rankings:
        h = getattr(r, "horizon", None) or (r.get("horizon") if isinstance(r, dict) else None) or "ros"
        src = getattr(r, "source", None) or (r.get("source") if isinstance(r, dict) else "")
        if horizon and h != horizon:
            continue
        if source and src != source:
            continue
        name = getattr(r, "player_name", None) or (r.get("player_name") or r.get("name") if isinstance(r, dict) else "")
        pos_raw = getattr(r, "position", None) or (r.get("position") if isinstance(r, dict) else "")
        pos = normalize_position(pos_raw or "")
        if positions is not None and pos not in positions:
            continue
        if pos in OMIT_RANK_POS:
            continue
        rank = getattr(r, "rank", None) if not isinstance(r, dict) else r.get("rank")
        rows.append(
            {
                "name": name,
                "position": pos,
                "rank": rank,
                "source": src,
                "horizon": h,
                "tier": getattr(r, "tier", None) if not isinstance(r, dict) else r.get("tier"),
            }
        )
    # Rank-first (positional boards): keep best players across RB/WR/TE/QB.
    rows.sort(key=lambda x: (int(x["rank"] or 999), x["position"] or "", x["name"] or ""))
    return rows[:limit]


def _roster_brief(
    team_name: str,
    rosters: list[Any],
    players: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rosters:
        if row.team_name != team_name:
            continue
        p = players.get(row.player_id)
        if not p:
            continue
        out.append(
            {
                "name": p.name,
                "position": normalize_position(p.position),
                "nfl_team": getattr(p, "nfl_team", "") or "",
                "slot": row.slot,
                "lineup_slot": getattr(row, "lineup_slot", "") or "",
            }
        )
    return out


def _news_for_context(news_items: list[Any], limit: int = 40) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for n in news_items[:limit]:
        if isinstance(n, dict):
            out.append(
                {
                    "player_id": n.get("player_id", ""),
                    "player_name": n.get("player_name") or n.get("name") or "",
                    "source": n.get("source", ""),
                    "headline": n.get("headline", ""),
                    "injury_flag": n.get("injury_flag") or n.get("flag") or "",
                }
            )
        else:
            out.append(
                {
                    "player_id": getattr(n, "player_id", ""),
                    "player_name": getattr(n, "player_name", "") or "",
                    "source": getattr(n, "source", ""),
                    "headline": getattr(n, "headline", ""),
                    "injury_flag": getattr(n, "injury_flag", "") or "",
                }
            )
    return out


def build_recommendation_context(
    *,
    team_name: str,
    hunt_positions: list[str],
    meta: Any,
    rosters: list[Any],
    players: dict[str, Any],
    standings: list[Any],
    rankings: list[Any],
    free_agents: list[dict[str, Any]],
    news_items: list[Any],
    include_start_sit: bool = True,
) -> dict[str, Any]:
    """Full structured payload — used for export / Claude paste; may be large."""
    hunt = [p for p in hunt_positions if p in TRADE_POS] or list(TRADE_POS)
    roster_slots = getattr(meta, "roster_slots", None) or "{}"

    # Prefer ROS consensus for weakness; fall back to any ROS rows.
    # Skill-only: DST/K omitted (never traded; previously starved the truncate window).
    ros_consensus = _rank_rows(rankings, horizon="ros", source="consensus", limit=200)
    if not ros_consensus:
        ros_consensus = _rank_rows(rankings, horizon="ros", limit=200)

    weekly_consensus = _rank_rows(rankings, horizon="weekly", source="consensus", limit=200)
    if not weekly_consensus:
        weekly_consensus = _rank_rows(rankings, horizon="weekly", limit=200)

    team_names = sorted({r.team_name for r in rosters})
    my_flags = weakness_flags_for_team(
        team_name, rosters, players, ros_consensus, roster_slots
    )
    league_flags = all_team_weakness_flags(
        team_names, rosters, players, ros_consensus, roster_slots
    )

    standings_brief = [
        {
            "team": s.team_name,
            "record": f"{s.wins}-{s.losses}-{s.ties}",
            "pf": round(float(s.points_for or 0), 1),
        }
        for s in standings
    ]

    # Cap FA list; skill positions only for trade/waiver context
    fa_brief = []
    for fa in free_agents:
        pos = normalize_position(fa.get("position") or "")
        if pos not in TRADE_POS:
            continue
        fa_brief.append(
            {
                "name": fa.get("name"),
                "position": pos,
                "nfl_team": fa.get("nfl_team") or "",
            }
        )
        if len(fa_brief) >= 80:
            break

    other_rosters = {
        t: _roster_brief(t, rosters, players)
        for t in team_names
        if t != team_name
    }

    return {
        "rules": {
            "never_trade_positions": sorted(NEVER_TRADE_POS),
            "hunt_positions": hunt,
            "include_start_sit": include_start_sit,
            "league_style": "12-team ESPN redraft (assume unless scoring says otherwise)",
        },
        "league": {
            "name": getattr(meta, "league_name", ""),
            "week": getattr(meta, "current_week", 1),
            "year": getattr(meta, "year", 0),
            "roster_slots": json.loads(roster_slots)
            if isinstance(roster_slots, str)
            else (roster_slots or {}),
            "standings": standings_brief,
        },
        "your_team": {
            "name": team_name,
            "roster": _roster_brief(team_name, rosters, players),
            "weakness_flags": my_flags,
        },
        "other_rosters": other_rosters,
        "league_weakness_flags": [
            f for f in league_flags if f.get("trade_relevant") or f.get("level") == "Weak"
        ],
        "rankings": {
            "ros_consensus_top": ros_consensus[:80],
            "weekly_consensus_top": weekly_consensus[:80],
            "ros_by_source_sample": {
                "fantasypros": _rank_rows(rankings, horizon="ros", source="fantasypros", limit=40),
                "sleeper": _rank_rows(rankings, horizon="ros", source="sleeper", limit=40),
                "espn": _rank_rows(rankings, horizon="ros", source="espn", limit=40),
            },
            "weekly_by_source_sample": {
                "fantasypros": _rank_rows(rankings, horizon="weekly", source="fantasypros", limit=30),
                "sleeper": _rank_rows(rankings, horizon="weekly", source="sleeper", limit=30),
                "espn": _rank_rows(rankings, horizon="weekly", source="espn", limit=30),
            },
        },
        "free_agents_skill": fa_brief,
        "news_injuries": _news_for_context(news_items, limit=50),
    }


def pack_context_for_llm(context: dict[str, Any]) -> dict[str, Any]:
    """
    LLM-bound payload: richer than the old heavily compacted JSON pack.

    TOON token savings let us restore nfl_team, more ranks, FA, and injuries
    while still fitting typical Ollama num_ctx. DST/K ranks stay omitted.
    """
    raw = json.loads(json.dumps(context, default=str))

    def slim_roster(roster: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": p.get("name"),
                "pos": p.get("position"),
                "nfl": p.get("nfl_team") or "",
                "slot": p.get("slot") or p.get("lineup_slot") or "",
            }
            for p in roster
        ]

    def slim_rank(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in rows:
            pos = normalize_position(r.get("position") or "")
            if pos in OMIT_RANK_POS:
                continue
            if pos not in SKILL_RANK_POS:
                continue
            out.append(
                {
                    "name": r.get("name"),
                    "pos": pos,
                    "rank": r.get("rank"),
                }
            )
            if len(out) >= limit:
                break
        return out

    your = raw.get("your_team") or {}
    ranks = raw.get("rankings") or {}
    ros = ranks.get("ros_consensus_top") or []
    weekly = ranks.get("weekly_consensus_top") or []
    by_src = ranks.get("ros_by_source_sample") or {}

    news_out: list[dict[str, Any]] = []
    for n in raw.get("news_injuries") or []:
        headline = (n.get("headline") or "").lower()
        flag = n.get("injury_flag") or ""
        if flag or any(x in headline for x in ("injur", "out", " ir", "doubt", "question", "suspend")):
            news_out.append(
                {
                    "player": n.get("player_name") or "",
                    "flag": flag,
                    "headline": (n.get("headline") or "")[:100],
                }
            )
        if len(news_out) >= 25:
            break

    packed = {
        "rules": raw.get("rules") or {},
        "league": {
            "name": (raw.get("league") or {}).get("name"),
            "week": (raw.get("league") or {}).get("week"),
            "year": (raw.get("league") or {}).get("year"),
            "roster_slots": (raw.get("league") or {}).get("roster_slots") or {},
            "standings": (raw.get("league") or {}).get("standings") or [],
        },
        "your_team": {
            "name": your.get("name"),
            "roster": slim_roster(your.get("roster") or []),
            "weakness_flags": [
                {
                    "position": f.get("position"),
                    "level": f.get("level"),
                    "best_player": f.get("best_player"),
                    "best_rank": f.get("best_rank"),
                    "why": f.get("why"),
                }
                for f in (your.get("weakness_flags") or [])
            ],
        },
        "other_rosters": {
            t: slim_roster(r) for t, r in (raw.get("other_rosters") or {}).items()
        },
        "league_weakness_flags": [
            {
                "team": f.get("team"),
                "position": f.get("position"),
                "level": f.get("level"),
                "best_player": f.get("best_player"),
                "best_rank": f.get("best_rank"),
            }
            for f in (raw.get("league_weakness_flags") or [])[:40]
        ],
        "rankings": {
            "ros_top": slim_rank(ros, 70),
            "weekly_top": slim_rank(weekly, 55),
            "ros_fantasypros": slim_rank(by_src.get("fantasypros") or [], 25),
            "ros_sleeper": slim_rank(by_src.get("sleeper") or [], 25),
        },
        "free_agents_skill": [
            {
                "name": f.get("name"),
                "pos": f.get("position"),
                "nfl": f.get("nfl_team") or "",
            }
            for f in (raw.get("free_agents_skill") or [])[:50]
        ],
        "news_injuries": news_out,
    }
    packed["_packing"] = {
        "note": (
            "Packed for LLM (skill ranks only; DST/K omitted). "
            "Wire format is TOON by default — export JSON is untruncated full context."
        ),
        "full_context_chars": len(json.dumps(context, default=str)),
        "format": context_format(),
    }
    return packed


# Back-compat alias used by tests / older callers
compact_context_for_llm = pack_context_for_llm


def encode_toon(data: dict[str, Any]) -> str:
    """Serialize a dict to TOON. Requires toon-format >= 0.9.0b1 (not the 0.1 stub)."""
    from toon_format import encode

    return encode(data)


def estimate_size(payload: dict[str, Any]) -> dict[str, Any]:
    """Char counts + rough token estimate (chars/4) for compact JSON vs TOON."""
    json_compact = json.dumps(payload, default=str, separators=(",", ":"))
    toon_text = encode_toon(payload)
    json_chars = len(json_compact)
    toon_chars = len(toon_text)
    json_tok = max(1, json_chars // 4)
    toon_tok = max(1, toon_chars // 4)
    return {
        "json_chars": json_chars,
        "toon_chars": toon_chars,
        "json_tokens_est": json_tok,
        "toon_tokens_est": toon_tok,
        "char_savings_pct": round(100.0 * (1 - toon_chars / json_chars), 1) if json_chars else 0.0,
        "token_savings_pct_est": round(100.0 * (1 - toon_tok / json_tok), 1) if json_tok else 0.0,
        "json_compact": json_compact,
        "toon": toon_text,
    }


SYSTEM_PROMPT = """You are a sharp fantasy football advisor for a 12-team ESPN redraft league.

The USER message includes league context in TOON (Token-Oriented Object Notation) or JSON.
TOON uses indentation and tabular arrays like:
  rankings.ros_top[3]{name,pos,rank}:
    Bijan Robinson,RB,1
    Ja'Marr Chase,WR,1
Read TOON the same way you would JSON objects/arrays. Field shortcuts: pos=position, nfl=NFL team, slot=lineup slot.

Return ONLY valid JSON (never TOON) matching this schema:
{
  "trades": [
    {
      "you_get": ["Player A"],
      "you_send": ["Player B"],
      "partner": "Team Name",
      "why": "One pitch-ready sentence"
    }
  ],
  "waivers": [
    {
      "add": "Player Name",
      "drop": "Player Name or null",
      "position": "RB|WR|TE",
      "why": "Short reason"
    }
  ],
  "start_sit": [
    {
      "start": "Player Name",
      "sit": "Player Name",
      "position": "RB|WR|TE|FLEX|QB|DST|K",
      "why": "Short reason using weekly ranks"
    }
  ],
  "notes": "Optional short caveats"
}

Hard rules:
- NEVER recommend trades involving QB, DST, or K (either side).
- Prefer hunt_positions for acquire targets.
- Use ROS ranks + weakness flags for trades/waivers; weekly ranks for start/sit.
- Prefer realistic win-win pitches over steals.
- Limit: up to 3 trades, 5 waivers, 3 start/sit. Keep each why to one short sentence.
- If data is thin, return fewer ideas and explain in notes — do not invent players not in context.
- Rankings in context are skill positions only (RB/WR/TE/QB); DST/K are omitted on purpose.
"""


def build_user_prompt(
    context: dict[str, Any],
    *,
    packed: bool = True,
    fmt: str | None = None,
) -> str:
    """Build the user message. Default: packed payload encoded as TOON."""
    payload = pack_context_for_llm(context) if packed else context
    wire = (fmt or context_format()).lower()
    if wire == "json":
        body = json.dumps(payload, default=str, separators=(",", ":"))
        intro = (
            "Using this league context JSON, propose trades, waivers, and optional start/sit. "
            "Respond with JSON only (schema in system prompt). "
            "Keep why fields to one short sentence. Max 3 trades, 5 waivers, 3 start/sit.\n\n"
        )
        return intro + body

    body = encode_toon(payload)
    intro = (
        "Using this league context in TOON (Token-Oriented Object Notation), "
        "propose trades, waivers, and optional start/sit. "
        "Respond with JSON only (schema in system prompt) — do not reply in TOON. "
        "Keep why fields to one short sentence. Max 3 trades, 5 waivers, 3 start/sit.\n\n"
        "```toon\n"
    )
    return intro + body + "\n```"


# Older callers used compact=True
def build_user_prompt_legacy(context: dict[str, Any], *, compact: bool = True) -> str:
    return build_user_prompt(context, packed=compact)

# FantasyAnalysis — Build Plan

## Scope

Local single-user fantasy football analyzer: ESPN league pull, multi-source **weekly + ROS** rankings fused into one board each, news/injuries, basic weakness flags, and **LLM recommendations** (Gemini-first). Read-only against ESPN; runs on your machine.

## Architecture (locked 2026-09-19)

**Keep / improve**

1. ESPN league pull — roster, standings, matchups, FA, roster slots
2. Rankings — FantasyPros + Sleeper (+ ESPN proj) → **RRF-fused** weekly + ROS boards
3. News / injury — ESPN public news API + Sleeper injury flags
4. Basic weakness flags — ROS depth vs starter slots
5. LLM recommendations — fused boards + flags/news → Gemini → trades/waivers

**Nuked**

- Heavy analytical trade finder (fairness engines, package constructors)
- Packing raw multi-source rank dumps into the LLM context
- Ollama as the default LLM path (legacy gated only)
- Never recommend QB / DST / K trades

**LLM runtime**

- Default: Google Gemini (`GEMINI_API_KEY` / `GOOGLE_API_KEY`, model `gemini-2.5-flash`)
- Optional: OpenAI / Anthropic via user API keys
- Graceful error if no key — UI still shows data + AI Studio setup link

## Phases shipped

| Phase | Status |
|---|---|
| 1 — ESPN + Streamlit + SQLite | shipped |
| 2 — FantasyPros + Sleeper + consensus | shipped (now RRF fusion) |
| 3 / 3.1 — Analytical trades/waivers | gutted |
| 4 — LLM-recs pivot | shipped |
| **5 — Rank fusion + Gemini** | **this slice** |

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| UI | Streamlit |
| League | `espn_api` (+ demo) |
| Rank fusion | RRF (default) / mean / median in `ingestion/consensus.py` |
| News | ESPN site API + Sleeper injuries |
| LLM | Gemini (`google-genai`) / OpenAI / Anthropic |
| Storage | SQLite via `sqlmodel` |

## Next (optional)

- Richer start/sit dedicated prompt
- Historical charts / weekly auto-refresh

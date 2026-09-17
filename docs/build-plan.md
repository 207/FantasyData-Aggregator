# FantasyAnalysis — Build Plan

## Scope

Local single-user fantasy football analyzer: ESPN league pull, multi-source **weekly + ROS** rankings, news/injuries, basic weakness flags, and **LLM recommendations** (Ollama-first). Read-only against ESPN; runs on your machine.

## Architecture (locked 2026-09-16)

**Keep / improve**

1. ESPN league pull — roster, standings, matchups, FA, roster slots
2. Rankings — weekly **and** ROS from FantasyPros + Sleeper (+ ESPN projections as third)
3. News / injury — ESPN public news API + Sleeper injury flags
4. Basic weakness flags — ROS depth vs starter slots
5. LLM recommendations — structured JSON context → trades + waivers (+ optional start/sit)

**Nuked**

- Heavy analytical trade finder (fairness engines, package constructors, long heuristics)
- Never recommend QB / DST / K trades

**LLM runtime**

- Default: Ollama (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`)
- Optional: OpenAI / Anthropic via user API keys
- Graceful error if no LLM (UI still shows data + setup instructions)

## Phases shipped

| Phase | Status |
|---|---|
| 1 — ESPN + Streamlit + SQLite | shipped |
| 2 — FantasyPros + Sleeper + consensus | shipped (extended to weekly/ROS) |
| 3 / 3.1 — Analytical trades/waivers | **gutted** — replaced by LLM path |
| **4 — LLM-recs pivot** | **this slice** |

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| UI | Streamlit |
| League | `espn_api` (+ demo) |
| Rankings | FantasyPros scrape + Sleeper + ESPN proj |
| News | ESPN site API + Sleeper injuries |
| LLM | Ollama / OpenAI / Anthropic |
| Storage | SQLite via `sqlmodel` |

## Next (optional)

- Remote Ollama on Windows RTX 3070
- Richer start/sit dedicated prompt
- Historical charts / weekly auto-refresh

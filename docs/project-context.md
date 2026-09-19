# FantasyAnalysis — Project context

## Local repo
- Path: `/Users/bennettsmolen/Fantasy`
- Branch: `main`
- GitHub: https://github.com/207/Fantasy.git
- Preference: normal git locally — **not** Origin
- Agents: run on Bennett’s Mac (`~/Fantasy` worker) by default — **no cloud agents** unless he asks

## Product
Local single-user fantasy football analyzer. **Pivot (2026-09-19):** ESPN + **RRF-fused** weekly/ROS rankings (FantasyPros + Sleeper + ESPN) + news/injuries + weakness flags → **Gemini recommendations** (free-tier AI Studio key). LLM context gets fused boards only — not raw multi-source dumps. Ollama no longer the default.

Plan: [build plan](./build-plan.md). Strategy: [trade strategy](./trade-strategy.md). Handoff: [internal/rank-fusion-gemini.md](../internal/rank-fusion-gemini.md).

## Locked decisions
- Never QB/DST/K trades
- **ROS** for trades/season value; **weekly** for start/sit
- Rank fusion default: **RRF** (`FUSION_METHOD=rrf`, `k=60`)
- LLM host: **Google Gemini** free tier (`GEMINI_API_KEY` / `GOOGLE_API_KEY`)
- Weakness flags only (no fancy package math) — LLM does the recommending

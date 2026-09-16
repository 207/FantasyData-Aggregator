# FantasyAnalysis — Build Plan

## Scope

Local single-user fantasy football analyzer: pull ESPN league data, grade the roster, and recommend trades/waivers with clear reasons. Read-only against ESPN; runs on your machine.

Source of truth: `docs/fantasy-football-analyzer-design.md` (repo).

## MVP slice (Phase 1 — this PR)

End-to-end local app you can run now:

- Streamlit dashboard with roster, standings, and matchup views
- SQLite persistence for league meta + roster snapshots
- ESPN adapter via `espn_api` when `SWID` / `espn_s2` / league id are set
- Demo mode with sample league data when ESPN credentials are absent (so the product is usable immediately)
- Manual **Refresh Data** that reloads adapters and rewrites SQLite

Out of scope for this slice: FantasyPros/Sleeper adapters, trade/waiver engines, news, scheduling.

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| UI | Streamlit |
| League data | `espn_api` (+ demo fallback) |
| Storage | SQLite via `sqlmodel` |
| Config | `.env` (gitignored) for ESPN cookies / league id / year |

## Next steps

1. **Phase 2** — FantasyPros + Sleeper adapters, consensus rankings, positional roster grades
2. **Phase 3** — Trade targets and waiver pickup recommendations with explainable “why”
3. **Phase 4** — News/injury flags, historical charts, optional weekly auto-refresh

# FantasyAnalysis — Build Plan

## Scope

Local single-user fantasy football analyzer: pull ESPN league data, grade the roster, and recommend trades/waivers with clear reasons. Read-only against ESPN; runs on your machine.

Source of truth: `docs/fantasy-football-analyzer-design.md` (repo).

## Phase 1 — shipped

End-to-end local app:

- Streamlit dashboard with roster, standings, and matchup views
- SQLite persistence for league meta + roster snapshots
- ESPN adapter via `espn_api` when `SWID` / `espn_s2` / league id are set
- Demo mode with sample league data when ESPN credentials are absent
- Manual **Refresh Data** that reloads adapters and rewrites SQLite
- D/ST position normalization (`D/ST` → `DST`) so defense grades correctly

## Phase 2 — shipped

- FantasyPros adapter (live scrape + mock fallback)
- Sleeper adapter (public search-rank board + trending adds log)
- Consensus rankings (weighted FP + Sleeper) persisted in SQLite
- Positional roster grades vs replacement level (depth fallback if ranks missing)
- UI: **Consensus ranks** tab + richer grade “why”
- Config: `RANKINGS_MODE`, `SLEEPER_ENABLED`, `FANTASYPROS_RANKINGS_URL`

## Phase 3 — shipped (this slice)

- Trade target finder: prefers RB/WR/TE (Weak then Average / FLEX depth); QB/DST/K only for clear holes with elite upgrades — avoids streaming-slot spam; surplus depth + offer hint from Strong (preferably skill) spots
- Waiver finder: ESPN/demo free-agent pool merged with unrostered consensus names; Sleeper trending boost
- Free agents + trending persisted on league meta (`free_agents_json`, `trending_json`)
- UI: **Trade targets** and **Waiver pickups** tabs with full readable “why” (same pattern as grades)
- Demo FA pool + mock ranks for offline recommendations

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| UI | Streamlit |
| League data | `espn_api` (+ demo fallback) |
| Rankings | FantasyPros scrape + Sleeper API (+ mock) |
| Storage | SQLite via `sqlmodel` |
| Config | `.env` (gitignored) for ESPN cookies / league id / year / rankings |

## Next steps

1. **Phase 4** — News/injury flags, historical charts, optional weekly auto-refresh

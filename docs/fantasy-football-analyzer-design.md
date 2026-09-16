# Fantasy Football Analyzer — Design Doc

## 1. Overview

A local desktop application that:
1. Pulls your ESPN fantasy league data (roster, matchups, standings, transactions).
2. Aggregates weekly rankings, projections, and player news from multiple public sources.
3. Analyzes your roster to surface strengths/weaknesses by position.
4. Recommends trade targets and waiver-wire pickups based on roster gaps and market rankings.

Runs entirely on your machine — no cloud hosting, no external accounts beyond ESPN and the public data sources it reads.

## 2. Goals / Non-Goals

**Goals**
- Single-command local startup, refreshable on demand.
- Read-only against ESPN (no lineup changes, no transactions performed automatically).
- Clear, explainable recommendations (show *why* a player is flagged), not a black box.
- Resilient to one data source going down — degrade gracefully, don't crash.

**Non-goals**
- No auto-drafting, auto-lineup-setting, or auto-waiver claims.
- No multi-user/multi-league SaaS deployment — this is a single-user local tool.
- No live in-game win probability tracking (weekly cadence, not real-time).

## 3. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Best library support for scraping/analysis; `espn_api` package exists specifically for this |
| League data | [`espn_api`](https://github.com/cwendt94/espn-api) (unofficial ESPN Fantasy client) | Handles ESPN's private-league auth and endpoints |
| External data | `requests` + `httpx`, `BeautifulSoup4`/`lxml` for scraping, feed parsing for RSS | Pulls rankings/news from multiple public sites |
| Storage | SQLite (via `sqlmodel` or plain `sqlite3`) | Zero-setup local persistence, easy to inspect/query |
| Analysis | `pandas` | Roster comparisons, ranking aggregation, positional scoring |
| UI | `Streamlit` | Fast to build, good at tables/charts, runs locally with `streamlit run app.py`, no frontend build step |
| Scheduling | Simple in-app "Refresh Data" button + optional `APScheduler` for a weekly auto-pull | Keep it manual-first; automate later if useful |

Everything ships as one Python project with a `requirements.txt` and a single entry point.

## 4. Authentication: Getting ESPN Data from the Browser

ESPN private leagues aren't exposed through a public API — `espn_api` authenticates using two cookies pulled from your browser session: `SWID` and `espn_s2`.

**Flow:**
1. You log into ESPN Fantasy in your browser as normal.
2. A one-time setup script (or a "Connect ESPN" button in the Streamlit UI) instructs you to open DevTools → Application → Cookies → `fantasy.espn.com`, and paste in `SWID` and `espn_s2`.
3. These are stored locally in a `.env` file (gitignored) or an encrypted local config — never transmitted anywhere except to ESPN's own endpoints.
4. `espn_api.football.League(league_id, year, espn_s2, swid)` handles all subsequent reads: roster, matchups, standings, free agents, transaction log.

This avoids browser automation (Selenium/Playwright) entirely for the ESPN side, which is more fragile and slower. Browser automation is kept as a fallback only if `espn_api` breaks against a future ESPN API change.

## 5. External Data Sources

| Source | What it provides | Method |
|---|---|---|
| FantasyPros | Consensus expert rankings (ROS + weekly), ADP | Scrape public rankings pages (no auth needed for standard views) |
| ESPN News/Player pages | Injury designations, beat-writer notes | `espn_api` player objects + light scraping for full articles |
| Sleeper API | Trending adds/drops, public player metadata | Free public API, no auth |
| NFL.com or a weather API | Game-time weather for outdoor stadiums (optional, phase 2) | Public API |

Design principle: each source is a **pluggable adapter** implementing a common interface (`fetch_rankings()`, `fetch_news()`, `fetch_trends()`). If FantasyPros changes its markup, only that adapter breaks — the rest of the pipeline keeps working, and the UI shows "source unavailable" instead of failing.

## 6. Architecture

```
┌─────────────────────┐
│   Streamlit UI       │  (dashboard, refresh button, trade/waiver views)
└──────────┬───────────┘
           │
┌──────────▼───────────┐
│   Analysis Engine     │  (roster strength scoring, gap detection,
│   (pandas)            │   trade/waiver recommendation logic)
└──────────┬───────────┘
           │
┌──────────▼───────────┐
│   Local SQLite DB     │  (players, rankings, roster snapshots, history)
└──────────┬───────────┘
           │
┌──────────▼───────────┐
│  Data Ingestion Layer │
│  ┌─────────────────┐  │
│  │ ESPN adapter     │  │  (espn_api, cookie auth)
│  │ FantasyPros      │  │  (scraper)
│  │ Sleeper          │  │  (REST API)
│  │ News adapters    │  │  (scraper/RSS)
│  └─────────────────┘  │
└───────────────────────┘
```

## 7. Data Model (SQLite)

- `players` — player_id, name, position, nfl_team
- `rankings` — player_id, source, week, rank, tier, projected_points, pulled_at
- `news` — player_id, source, headline, body, published_at
- `roster_snapshots` — team_id, player_id, week, slot (starter/bench/IR)
- `league_meta` — league_id, scoring_settings, roster_slots, team_names

Storing week-by-week snapshots (rather than overwriting) lets you later chart trends — e.g. "my RB2 spot has been below replacement level for 3 weeks."

## 8. Analysis Engine

**Roster strength/weakness scoring**
1. For each roster spot, pull your player's current consensus rank/tier (averaged across sources, weighted if you want to trust one source more).
2. Compare against positional replacement level (e.g. the rank of a typical streaming option at that position) and against league-mates' rosters if visible.
3. Output a per-position grade (e.g. "RB: Strong — 2 top-24 backs", "TE: Weak — starter ranked TE28").

**Trade targets**
- Identify your weakest 1–2 positions.
- Cross-reference other rosters in the league (ESPN exposes all teams' rosters) for players who are strong at a position where *they're* deep and you're not — classic "sell high on their surplus" logic.
- Rank candidates by rest-of-season projection delta vs. your current starter.

**Waiver pickups**
- Pull the free-agent pool from ESPN.
- Filter by your weak positions.
- Cross-reference Sleeper trending-adds and FantasyPros rankings to surface undervalued/rising players.
- Flag injury-driven opportunities from news adapter output.

## 9. Refresh & Caching

- Manual "Refresh" button in the UI pulls fresh data from all sources and re-runs analysis.
- Cache each source's data with a timestamp; if a source fails, fall back to last-cached data and show a staleness warning rather than blocking the whole refresh.
- Optional weekly auto-refresh (e.g. Tuesday morning after waivers process) via `APScheduler`, off by default.

## 10. Project Structure

```
fantasy-analyzer/
├── app.py                 # Streamlit entry point
├── config/.env             # ESPN cookies, league_id, year (gitignored)
├── ingestion/
│   ├── espn_adapter.py
│   ├── fantasypros_adapter.py
│   ├── sleeper_adapter.py
│   └── news_adapter.py
├── analysis/
│   ├── roster_grader.py
│   ├── trade_finder.py
│   └── waiver_finder.py
├── storage/
│   ├── db.py
│   └── models.py
├── requirements.txt
└── README.md
```

## 11. Build Phases

1. **Phase 1 — Core pipeline:** ESPN adapter + SQLite storage + basic Streamlit view of your roster. Get real data flowing end to end.
2. **Phase 2 — Rankings integration:** FantasyPros + Sleeper adapters, consensus scoring, roster grading by position.
3. **Phase 3 — Recommendations:** Trade target and waiver logic.
4. **Phase 4 — Polish:** News/injury integration, historical trend charts, auto-refresh scheduling.

## 12. Risks

- **`espn_api` is unofficial** — ESPN can change endpoints without notice, breaking the adapter. Mitigation: adapter isolation (Section 5) so a break is contained and visible, not silent.
- **Scraping fragility** — FantasyPros/other sites may change HTML structure. Same mitigation, plus consider paid APIs later if this becomes a recurring headache.
- **Cookie expiry** — ESPN cookies expire periodically; you'll need to re-paste them occasionally. UI should detect an auth failure and prompt you clearly rather than failing silently.

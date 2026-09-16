# FantasyAnalysis

Local fantasy football analyzer for your ESPN league. Pulls roster, standings, matchups, and multi-source rankings into SQLite and surfaces them in a Streamlit dashboard with explainable positional grades.

Design: [`docs/fantasy-football-analyzer-design.md`](docs/fantasy-football-analyzer-design.md)  
Build plan: [`docs/build-plan.md`](docs/build-plan.md)

## What works now (Phase 1 + Phase 2)

- Streamlit UI: roster, standings, matchups, consensus positional grades, consensus ranks, source status
- SQLite snapshots under `data/fantasy.db`
- Live ESPN via `espn_api` when cookies are configured
- Demo league when ESPN credentials are missing
- FantasyPros rankings (live scrape with mock fallback) + Sleeper search-rank board
- Consensus ranks powering positional grades vs replacement level
- Manual **Refresh Data** in the sidebar

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.port 3847 --server.address 127.0.0.1
```

Open [http://127.0.0.1:3847](http://127.0.0.1:3847).

### Live ESPN (optional)

1. Copy `config/.env.example` → `config/.env`
2. Set `LEAGUE_ID`, `YEAR`, `SWID`, and `ESPN_S2` (from DevTools → Application → Cookies on `fantasy.espn.com`)
3. Optionally set `TEAM_NAME` to highlight your club
4. Click **Refresh Data**

Credentials stay on your machine and are only sent to ESPN.

### Rankings config

| Variable | Default | Purpose |
|---|---|---|
| `RANKINGS_MODE` | `live` | `live` tries FantasyPros scrape + Sleeper; `mock` uses built-in FP ranks only |
| `SLEEPER_ENABLED` | `true` | Set `false` to skip Sleeper |
| `FANTASYPROS_RANKINGS_URL` | FantasyPros consensus cheatsheet | Override rankings URL |

If FantasyPros HTML changes, refresh still succeeds with mock ranks and a `stale` status in **Source status**.

## Project layout

```
app.py                 # Streamlit entry
ingestion/             # ESPN, FantasyPros, Sleeper, consensus, demo
analysis/              # Roster grading (consensus + depth fallback)
storage/               # SQLite models + persistence
config/.env.example    # Credential + rankings template
docs/                  # Design + build plan
```

## Next

Phase 3 adds trade targets and waiver recommendations with explainable “why”.

# FantasyAnalysis

Local fantasy football analyzer for your ESPN league. Pulls roster, standings, and matchups into SQLite and surfaces them in a Streamlit dashboard with explainable positional grades.

Design: [`docs/fantasy-football-analyzer-design.md`](docs/fantasy-football-analyzer-design.md)  
Build plan: [`docs/build-plan.md`](docs/build-plan.md)

## What works now (Phase 1)

- Streamlit UI: roster, standings, matchups, positional depth grades, source status
- SQLite snapshots under `data/fantasy.db`
- Live ESPN via `espn_api` when cookies are configured
- Demo league when ESPN credentials are missing (usable out of the box)
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

## Project layout

```
app.py                 # Streamlit entry
ingestion/             # ESPN adapter + demo fallback
analysis/              # Roster grading (Phase 1 depth-based)
storage/               # SQLite models + persistence
config/.env.example    # Credential template
docs/                  # Design + build plan
```

## Next

Phase 2 adds FantasyPros / Sleeper rankings and consensus grades. Phase 3 adds trade and waiver recommendations.

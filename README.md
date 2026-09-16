# FantasyAnalysis

Local fantasy football analyzer for your ESPN league. Pulls roster, standings, matchups, and multi-source rankings into SQLite and surfaces them in a Streamlit dashboard with explainable grades, trade targets, and waiver pickups.

Design: [`docs/fantasy-football-analyzer-design.md`](docs/fantasy-football-analyzer-design.md)  
Build plan: [`docs/build-plan.md`](docs/build-plan.md)

## What works now (Phase 1–3)

- Streamlit UI: roster, standings, matchups, positional grades, **trade targets**, **waiver pickups**, consensus ranks, source status
- SQLite snapshots under `data/fantasy.db` (includes free-agent pool + Sleeper trending)
- Live ESPN via `espn_api` when cookies are configured (rosters + free agents)
- Demo league when ESPN credentials are missing
- FantasyPros rankings (live scrape with mock fallback) + Sleeper search-rank board
- Consensus ranks powering grades, trades, and waivers
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

### Recommendations

- **Trade targets** — multi-select hunt positions (default RB/WR/TE). Shop upgrades even when you grade Strong. Prefers counterparties who are Weak where you have surplus (“fill their hole”) and suggests an offer hint.
- **Waiver pickups** — same hunt-position filter over ESPN/demo FA pool + unrostered consensus names; Sleeper trending boost. Full “why” under each table (scrollable long cells).
- **Waiver pickups** — ESPN/demo free agents plus unrostered consensus names; Sleeper trending adds are boosted. Full “why” text renders below each table (not clipped in cells).

## Project layout

```
app.py                 # Streamlit entry
ingestion/             # ESPN, FantasyPros, Sleeper, consensus, demo
analysis/              # Roster grades, trade finder, waiver finder
storage/               # SQLite models + persistence
config/.env.example    # Credential + rankings template
docs/                  # Design + build plan
```

## Next

Phase 4 adds news/injury flags, historical charts, and optional weekly auto-refresh.

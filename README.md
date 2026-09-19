# FantasyAnalysis

Local ESPN fantasy analyzer: league data + **fused weekly/ROS rankings** + news/injuries + basic weakness flags → **LLM recommendations** (Google Gemini by default).

Design notes: [`docs/fantasy-football-analyzer-design.md`](docs/fantasy-football-analyzer-design.md) · Build plan: [`docs/build-plan.md`](docs/build-plan.md)

## Architecture (current)

| Keep | Role |
|---|---|
| ESPN pull | Rosters, standings, matchups, free agents, roster slots |
| Rank fusion | FantasyPros + Sleeper (+ ESPN proj) → one **weekly** + one **ROS** board via **RRF** (default) |
| News / injury | ESPN public news API + Sleeper `injury_status` |
| Weakness flags | Simple ROS depth vs starter slots (no package math) |
| LLM recs | Fused boards + league/flags/news → Gemini (TOON/JSON) → JSON trades + waivers |

**Removed:** heavy analytical trade finder; packing raw multi-source ranks into the LLM; Ollama as the default LLM path. QB/DST/K trades are never recommended.

## Rank fusion (why RRF)

Sources disagree on absolute ranks and coverage. **Reciprocal Rank Fusion** scores each player as `Σ 1/(k + rank_s)` (default `k=60`) across FantasyPros, Sleeper, and ESPN when present, then re-ranks within position. That rewards agreement near the top without needing calibrated score scales. Optional `FUSION_METHOD=mean` or `median` averages ranks instead.

## Run the app

Prefer the project venv (Homebrew `python@3.14` on this Mac):

```bash
cd /Users/bennettsmolen/Fantasy
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.port 3847 --server.address 127.0.0.1
```

Open [http://127.0.0.1:3847](http://127.0.0.1:3847).

If **Refresh Data** fails every live source with `No module named 'importlib.resources'`, the venv or a long-lived Streamlit process is pointing at a removed Homebrew Python build. Stop Streamlit, recreate `.venv`, reinstall requirements, and start again.

```bash
lsof -nP -iTCP:3847 -sTCP:LISTEN
pkill -f 'streamlit run app.py'   # only if you intend to stop FantasyAnalysis
```

## Google Gemini (default LLM)

1. Open [Google AI Studio](https://aistudio.google.com/apikey) → **Get API key** → create a key (free tier).
2. Put it in `config/.env`:

```bash
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
# or: GOOGLE_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.8-flash   # best free-tier Flash; lite: gemini-3.5-flash-lite
LLM_CONTEXT_FORMAT=toon         # toon (default) | json
FUSION_METHOD=rrf
FUSION_RRF_K=60
```

3. In the app: **Refresh Data** → **LLM recommendations** → **Generate recommendations**.

The UI sends a **TOON** pack with **fused** weekly + ROS skill ranks (not raw FantasyPros/Sleeper dumps), plus league/flags/news. Use **Download full context JSON** for Claude-in-browser, or **Download packed TOON**. If the key is missing, the app shows setup instructions and still lets you export context.

### Optional other providers

Set `LLM_PROVIDER=openai` or `anthropic` with your own API keys. No Cursor keys are used.

## ESPN (optional)

1. Copy `config/.env.example` → `config/.env`
2. Set `LEAGUE_ID`, `YEAR`, `SWID`, `ESPN_S2`
3. Optionally `TEAM_NAME`
4. **Refresh Data**

Without cookies, demo league data is used.

## Rankings & news sources

| Source | Weekly | ROS | Notes |
|---|---|---|---|
| FantasyPros | scrape PPR weekly | scrape ROS PPR overall | mock fallback |
| Sleeper | trending buzz board | `search_rank` | free API |
| ESPN | projected points | same when available | third source; live league only |
| **Fused board** | RRF / mean / median | same | what Rankings tab + LLM use |
| ESPN news | — | — | `site.api.espn.com` headlines |
| Sleeper injury | — | — | `injury_status` flags |

## UI tabs

- **League** — roster / standings / matchups / FA
- **Rankings** — fused weekly vs ROS (per-source in expander)
- **Injuries / news**
- **Weakness flags** — positional Weak/Thin/OK
- **LLM recommendations/export** — JSON/TOON download anytime + Gemini generate
- **Source status**

## Project layout

```
app.py                 # Streamlit UI
analysis/              # weakness flags, LLM client/context/recs
ingestion/             # ESPN, FantasyPros, Sleeper, news, rank fusion (consensus.py)
storage/               # SQLite
config/.env.example    # ESPN + Gemini + fusion
```

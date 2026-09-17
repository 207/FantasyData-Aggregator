# FantasyAnalysis

Local ESPN fantasy analyzer: league data + **weekly/ROS multi-source rankings** + news/injuries + basic weakness flags → **LLM recommendations** (Ollama by default).

Design notes: [`docs/fantasy-football-analyzer-design.md`](docs/fantasy-football-analyzer-design.md) · Build plan: [`docs/build-plan.md`](docs/build-plan.md)

## Architecture (current)

| Keep | Role |
|---|---|
| ESPN pull | Rosters, standings, matchups, free agents, roster slots |
| Rankings | **Weekly** and **ROS** from FantasyPros + Sleeper (+ ESPN projected points when present) |
| News / injury | ESPN public news API + Sleeper `injury_status` |
| Weakness flags | Simple ROS depth vs starter slots (no package math) |
| LLM recs | Structured JSON context → trades + waivers (+ optional start/sit) |

**Removed:** heavy analytical trade finder (1-for-1 fairness, 2-for-1 constructors, long scoring heuristics). QB/DST/K trades are never recommended.

## Run the app

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py --server.port 3847 --server.address 127.0.0.1
```

Open [http://127.0.0.1:3847](http://127.0.0.1:3847).

## Ollama (default LLM)

1. Install from [ollama.com](https://ollama.com)
2. Pull a 7B–14B model for a ~24GB Mac, e.g.:

```bash
ollama pull llama3.1:8b
# alternatives: mistral, qwen2.5:14b, llama3.2:3b (lighter)
```

3. Copy `config/.env.example` → `config/.env` and set:

```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1:8b
```

4. In the app: **Refresh Data**, open **LLM recommendations**, click **Generate recommendations**.

If Ollama is down, the app still shows league/ranks/flags and prints setup instructions — it does not crash.

### Optional cloud LLMs

Set `LLM_PROVIDER=openai` or `anthropic` and your own `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in `config/.env`. No Cursor keys are used.

### Optional remote Ollama (Windows RTX 3070)

Later you can run Ollama on a Windows box with an RTX 3070 and point `OLLAMA_BASE_URL` at that host (e.g. `http://192.168.x.x:11434`) for faster ~7B inference.

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
| ESPN news | — | — | `site.api.espn.com` headlines |
| Sleeper injury | — | — | `injury_status` flags |

## UI tabs

- **League** — roster / standings / matchups / FA
- **Rankings** — weekly vs ROS, filter by source
- **Injuries / news**
- **Weakness flags** — positional Weak/Thin/OK
- **LLM recommendations** — generate button + results
- **Source status**

## Project layout

```
app.py                 # Streamlit UI
analysis/              # weakness flags, LLM client/context/recs (thin trade helpers)
ingestion/             # ESPN, FantasyPros, Sleeper, ESPN ranks, news, consensus
storage/               # SQLite
config/.env.example    # ESPN + LLM + rankings
```

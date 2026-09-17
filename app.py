from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _require_stdlib_resources() -> None:
    """Fail fast when Homebrew upgraded Python out from under a long-lived process/venv."""
    try:
        import importlib.resources as _resources  # noqa: F401
    except ModuleNotFoundError as exc:
        base = getattr(sys, "base_prefix", "") or ""
        raise RuntimeError(
            "Python stdlib is broken in this process "
            f"(cannot import importlib.resources: {exc}). "
            "Usually Homebrew upgraded python@3.14 while Streamlit was still running, "
            "or `.venv` still points at a removed Cellar build. "
            "Fix: stop Streamlit, recreate `.venv` with the current interpreter, "
            f"reinstall requirements, and restart. base_prefix={base!r} "
            f"executable={sys.executable!r}"
        ) from exc


_require_stdlib_resources()

from analysis import recommendations as recommendations_mod
from analysis import trade_finder as trade_finder_mod
from analysis import waiver_finder as waiver_finder_mod
from analysis import weakness as weakness_mod
from analysis.llm_client import describe_setup

recommendations_mod = importlib.reload(recommendations_mod)
trade_finder_mod = importlib.reload(trade_finder_mod)
waiver_finder_mod = importlib.reload(waiver_finder_mod)
weakness_mod = importlib.reload(weakness_mod)

generate_recommendations = recommendations_mod.generate_recommendations
CORE_POS = trade_finder_mod.CORE_POS
HUNT_POS_OPTIONS = trade_finder_mod.HUNT_POS_OPTIONS
DEFAULT_HUNT_POS = trade_finder_mod.DEFAULT_HUNT_POS
skill_free_agents = waiver_finder_mod.skill_free_agents
weakness_flags_for_team = weakness_mod.weakness_flags_for_team
all_team_weakness_flags = weakness_mod.all_team_weakness_flags

from ingestion.espn_adapter import espn_configured, load_config
from ingestion.refresh import fetch_league
from storage.db import init_db, load_dashboard, upsert_league_snapshot

st.set_page_config(
    page_title="FantasyAnalysis",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def ensure_data(force_refresh: bool = False, force_demo: bool = False) -> dict:
    init_db()
    dash = load_dashboard()
    if force_refresh or dash.get("meta") is None:
        payload = fetch_league(force_demo=force_demo)
        upsert_league_snapshot(payload)
        dash = load_dashboard()
    return dash


def status_badge(mode: str) -> str:
    if mode == "espn":
        return "🟢 Live ESPN"
    return "🟡 Demo mode"


def _rank_table(ranking_rows, *, horizon: str, source_filter: str | None = None) -> pd.DataFrame:
    rows = []
    for r in ranking_rows:
        h = getattr(r, "horizon", None) or "ros"
        if h != horizon:
            continue
        src = getattr(r, "source", "") or ""
        if source_filter and src != source_filter:
            continue
        rows.append(
            {
                "Rank": r.rank,
                "Player": r.player_name or r.player_id,
                "Pos": r.position or "—",
                "Tier": r.tier if r.tier is not None else "—",
                "Source": src,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    st.title("FantasyAnalysis")
    st.caption(
        "ESPN league data + multi-source weekly/ROS ranks + news → LLM trade & waiver ideas."
    )

    cfg = load_config()
    with st.sidebar:
        st.header("Data")
        st.write(
            "Live ESPN"
            if espn_configured(cfg)
            else "Demo league (no ESPN cookies configured)"
        )
        st.caption(f"Rankings mode: **{cfg.get('rankings_mode', 'live')}**")
        if st.button("Refresh Data", type="primary", use_container_width=True):
            with st.spinner("Pulling league, rankings, news…"):
                ensure_data(force_refresh=True)
            st.success("Refresh complete.")
            st.rerun()

        if espn_configured(cfg) and st.button("Load demo instead", use_container_width=True):
            ensure_data(force_refresh=True, force_demo=True)
            st.rerun()

        st.divider()
        st.subheader("Connect ESPN")
        st.markdown(
            "Copy `config/.env.example` → `config/.env` and set `LEAGUE_ID`, `YEAR`, "
            "`SWID`, and `ESPN_S2` from fantasy.espn.com cookies. Then **Refresh Data**."
        )
        st.subheader("LLM")
        st.caption(describe_setup())
        if cfg.get("team_name"):
            st.caption(f"Preferred team: **{cfg['team_name']}**")

    dash = ensure_data()
    meta = dash.get("meta")
    if not meta:
        st.error("No league data available.")
        return

    players = dash["players"]
    rosters = dash["rosters"]
    standings = dash["standings"]
    matchups = dash["matchups"]
    logs = dash["logs"]
    ranking_rows = dash.get("rankings") or []
    free_agents = dash.get("free_agents") or []
    trending = dash.get("trending") or []
    news_items = dash.get("news") or []

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("League", meta.league_name or meta.league_id)
    c2.metric("Week", meta.current_week)
    c3.metric("Season", meta.year)
    c4.metric("Source", status_badge(meta.source_mode))
    st.caption(f"Last refreshed: {meta.refreshed_at}")

    team_names = sorted({r.team_name for r in rosters}) or sorted(
        {s.team_name for s in standings}
    )
    preferred = cfg.get("team_name") or (team_names[0] if team_names else "")
    default_idx = team_names.index(preferred) if preferred in team_names else 0

    ros_for_flags = []
    for r in ranking_rows:
        if getattr(r, "horizon", "ros") != "ros":
            continue
        if r.source != "consensus":
            continue
        ros_for_flags.append(
            {
                "name": r.player_name or r.player_id,
                "position": r.position,
                "rank": r.rank,
                "tier": r.tier,
                "source": "consensus",
                "horizon": "ros",
            }
        )
    if not ros_for_flags:
        for r in ranking_rows:
            if getattr(r, "horizon", "ros") != "ros":
                continue
            ros_for_flags.append(
                {
                    "name": r.player_name or r.player_id,
                    "position": r.position,
                    "rank": r.rank,
                    "source": r.source,
                    "horizon": "ros",
                }
            )

    (
        tab_league,
        tab_ranks,
        tab_news,
        tab_weak,
        tab_recs,
        tab_status,
    ) = st.tabs(
        [
            "League",
            "Rankings",
            "Injuries / news",
            "Weakness flags",
            "LLM recommendations",
            "Source status",
        ]
    )

    with tab_league:
        sub_r, sub_s, sub_m, sub_fa = st.tabs(["Roster", "Standings", "Matchups", "Free agents"])
        with sub_r:
            if not team_names:
                st.info("No rosters in the current snapshot.")
            else:
                team = st.selectbox("Team", team_names, index=default_idx)
                rows = []
                for r in rosters:
                    if r.team_name != team:
                        continue
                    p = players.get(r.player_id)
                    rows.append(
                        {
                            "Slot": r.slot,
                            "Lineup": r.lineup_slot or "—",
                            "Player": p.name if p else r.player_id,
                            "Pos": p.position if p else "—",
                            "NFL": p.nfl_team if p else "—",
                        }
                    )
                df = pd.DataFrame(rows)
                if not df.empty:
                    order = {"starter": 0, "bench": 1, "IR": 2}
                    df["_o"] = df["Slot"].map(lambda s: order.get(s, 9))
                    df = df.sort_values(["_o", "Pos", "Player"]).drop(columns=["_o"])
                st.dataframe(df, use_container_width=True, hide_index=True)
        with sub_s:
            srows = [
                {
                    "Team": s.team_name,
                    "W": s.wins,
                    "L": s.losses,
                    "T": s.ties,
                    "PF": round(s.points_for, 1),
                    "PA": round(s.points_against, 1),
                }
                for s in standings
            ]
            sdf = pd.DataFrame(srows)
            if not sdf.empty:
                sdf = sdf.sort_values(["W", "PF"], ascending=[False, False])
            st.dataframe(sdf, use_container_width=True, hide_index=True)
        with sub_m:
            mrows = [
                {
                    "Week": m.week,
                    "Home": m.home_team_name,
                    "Home score": round(m.home_score, 1),
                    "Away": m.away_team_name,
                    "Away score": round(m.away_score, 1),
                }
                for m in matchups
            ]
            st.dataframe(pd.DataFrame(mrows), use_container_width=True, hide_index=True)
            if not mrows:
                st.info("No matchups for this week yet.")
        with sub_fa:
            fa_df = pd.DataFrame(skill_free_agents(free_agents, list(CORE_POS), limit=80))
            if fa_df.empty:
                st.info("No skill-position free agents in snapshot.")
            else:
                st.dataframe(fa_df, use_container_width=True, hide_index=True)
            if trending:
                st.caption("Sleeper trending: " + ", ".join(trending[:15]))

    with tab_ranks:
        st.markdown(
            "Weekly vs rest-of-season boards from FantasyPros + Sleeper "
            "(+ ESPN projected points when available). Persist separately; switch below."
        )
        horizon = st.radio("Horizon", ["ros", "weekly"], horizontal=True, format_func=lambda x: "ROS" if x == "ros" else "Weekly")
        source = st.selectbox(
            "Source",
            ["consensus", "fantasypros", "fantasypros_mock", "sleeper", "espn", "all"],
            index=0,
        )
        if source == "all":
            rdf = _rank_table(ranking_rows, horizon=horizon)
        else:
            rdf = _rank_table(ranking_rows, horizon=horizon, source_filter=source)
        if rdf.empty:
            st.info("No rankings for this horizon/source — try Refresh Data.")
        else:
            positions = sorted({p for p in rdf["Pos"].tolist() if p != "—"})
            default_pos = [p for p in ["QB", "RB", "WR", "TE", "DST", "K"] if p in positions] or positions
            pos_filter = st.multiselect("Positions", positions, default=default_pos)
            if pos_filter:
                rdf = rdf[rdf["Pos"].isin(pos_filter)]
            st.dataframe(
                rdf.sort_values(["Pos", "Rank", "Source"]),
                use_container_width=True,
                hide_index=True,
            )

    with tab_news:
        st.markdown(
            "News from **ESPN public site API** (`site.api.espn.com`) + injury flags from "
            "**Sleeper** `injury_status`. Attached to players when names match."
        )
        nrows = [
            {
                "Flag": getattr(n, "injury_flag", "") or "—",
                "Player": getattr(n, "player_name", "") or "—",
                "Source": n.source,
                "Headline": n.headline,
            }
            for n in news_items
        ]
        if not nrows:
            st.info("No news/injury items yet — Refresh Data.")
        else:
            st.dataframe(pd.DataFrame(nrows), use_container_width=True, hide_index=True)

    with tab_weak:
        st.markdown(
            "Simple positional weakness from **ROS depth vs starter slots** "
            "(ESPN `roster_slots` when present). Trade-relevant = RB/WR/TE Weak/Thin only."
        )
        if not team_names:
            st.info("No teams loaded.")
        else:
            scope = st.radio("Scope", ["Your team", "All teams"], horizontal=True)
            if scope == "Your team":
                wt = st.selectbox("Team", team_names, index=default_idx, key="weak_team")
                flags = weakness_flags_for_team(
                    wt, rosters, players, ros_for_flags, meta.roster_slots
                )
            else:
                flags = all_team_weakness_flags(
                    team_names, rosters, players, ros_for_flags, meta.roster_slots
                )
            only_trade = st.checkbox("Trade-relevant only (RB/WR/TE Weak/Thin)", value=False)
            if only_trade:
                flags = [f for f in flags if f.get("trade_relevant")]
            fdf = pd.DataFrame(
                [
                    {
                        "Team": f["team"],
                        "Pos": f["position"],
                        "Level": f["level"],
                        "Slots": f["starter_slots"],
                        "Rostered": f["rostered"],
                        "Startable": f["startable"],
                        "Best": f.get("best_player") or "—",
                        "Best ROS": f["best_rank"] if f.get("best_rank") is not None else "—",
                        "Why": f["why"],
                    }
                    for f in flags
                ]
            )
            st.dataframe(fdf, use_container_width=True, hide_index=True)

    with tab_recs:
        st.markdown(
            "Builds structured league context (rosters, weekly + ROS ranks, injuries, "
            "weakness flags, hunt positions) and asks the LLM for trade + waiver ideas. "
            "**Never recommends QB/DST/K trades.** Start/sit uses weekly ranks when included."
        )
        if not team_names:
            st.info("Load league data first.")
        else:
            rec_team = st.selectbox("Your team", team_names, index=default_idx, key="rec_team")
            hunt = st.multiselect(
                "Hunt positions (passed to LLM)",
                options=list(HUNT_POS_OPTIONS),
                default=list(DEFAULT_HUNT_POS),
                key="rec_hunt",
            )
            include_ss = st.checkbox("Include start/sit", value=True)
            if st.button("Generate recommendations", type="primary"):
                with st.spinner("Calling LLM…"):
                    out = generate_recommendations(
                        team_name=rec_team,
                        hunt_positions=hunt,
                        meta=meta,
                        rosters=rosters,
                        players=players,
                        standings=standings,
                        rankings=ranking_rows,
                        free_agents=free_agents,
                        news_items=news_items,
                        include_start_sit=include_ss,
                    )
                st.session_state["llm_recs"] = out

            out = st.session_state.get("llm_recs")
            if out:
                if out.get("ok") and out.get("result"):
                    res = out["result"]
                    if res.get("notes"):
                        st.info(res["notes"])
                    st.subheader("Trades")
                    trades = res.get("trades") or []
                    if not trades:
                        st.write("No trades returned.")
                    else:
                        for t in trades:
                            get = ", ".join(t.get("you_get") or []) or "—"
                            send = ", ".join(t.get("you_send") or []) or "—"
                            st.markdown(
                                f"**You get {get}** ← send **{send}** to **{t.get('partner') or '?'}**  \n"
                                f"{t.get('why') or ''}"
                            )
                    st.subheader("Waivers")
                    waivers = res.get("waivers") or []
                    if not waivers:
                        st.write("No waivers returned.")
                    else:
                        wdf = pd.DataFrame(
                            [
                                {
                                    "Add": w.get("add"),
                                    "Drop": w.get("drop") or "—",
                                    "Pos": w.get("position") or "—",
                                    "Why": w.get("why") or "",
                                }
                                for w in waivers
                                if isinstance(w, dict)
                            ]
                        )
                        st.dataframe(wdf, use_container_width=True, hide_index=True)
                    if include_ss:
                        st.subheader("Start / sit")
                        ss = res.get("start_sit") or []
                        if not ss:
                            st.write("No start/sit returned.")
                        else:
                            sdf = pd.DataFrame(
                                [
                                    {
                                        "Start": s.get("start"),
                                        "Sit": s.get("sit"),
                                        "Pos": s.get("position") or "—",
                                        "Why": s.get("why") or "",
                                    }
                                    for s in ss
                                    if isinstance(s, dict)
                                ]
                            )
                            st.dataframe(sdf, use_container_width=True, hide_index=True)
                else:
                    st.error(out.get("error") or "LLM unavailable")
                    st.markdown(f"**Setup:** {out.get('setup') or describe_setup()}")
                    st.caption(
                        "Weakness flags and rankings still work without an LLM — "
                        "see other tabs."
                    )
                with st.expander("Context sent to LLM (JSON)"):
                    st.code(
                        json.dumps(out.get("context") or {}, indent=2, default=str)[:12000],
                        language="json",
                    )

    with tab_status:
        st.markdown("Adapter health from the last refresh — failures degrade to mock/cache.")
        lrows = [
            {
                "Source": log.source,
                "Status": log.status,
                "Message": log.message,
                "At": str(log.pulled_at),
            }
            for log in logs
        ]
        st.dataframe(pd.DataFrame(lrows), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()

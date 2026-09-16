from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.roster_grader import grade_roster
from analysis.trade_finder import find_trade_targets
from analysis.waiver_finder import find_waiver_pickups
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


def main() -> None:
    st.title("FantasyAnalysis")
    st.caption(
        "Local ESPN fantasy league analyzer — roster, grades, trades, and waivers."
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
            with st.spinner("Pulling league + rankings…"):
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
            "`SWID`, and `ESPN_S2` from fantasy.espn.com cookies. Then hit **Refresh Data**."
        )
        st.markdown(
            "Optional rankings: `RANKINGS_MODE=live|mock`, `SLEEPER_ENABLED=true`, "
            "`FANTASYPROS_RANKINGS_URL=…`."
        )
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

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("League", meta.league_name or meta.league_id)
    c2.metric("Week", meta.current_week)
    c3.metric("Season", meta.year)
    c4.metric("Source", status_badge(meta.source_mode))

    st.caption(f"Last refreshed: {meta.refreshed_at}")

    team_names = sorted({r.team_name for r in rosters}) or sorted({s.team_name for s in standings})
    preferred = cfg.get("team_name") or (team_names[0] if team_names else "")
    default_idx = team_names.index(preferred) if preferred in team_names else 0

    consensus_for_grade: list[dict] = []
    consensus_table: list[dict] = []
    for r in ranking_rows:
        if r.source != "consensus":
            continue
        player = players.get(r.player_id)
        name = (r.player_name or (player.name if player else "") or str(r.player_id)).strip()
        pos = (r.position or (player.position if player else "") or "").strip()
        consensus_for_grade.append(
            {"name": name, "position": pos or "?", "rank": r.rank, "tier": r.tier, "source": "consensus"}
        )
        consensus_table.append({"Rank": r.rank, "Player": name, "Pos": pos or "—", "Tier": r.tier or "—"})

    tab_roster, tab_standings, tab_matchups, tab_grades, tab_trades, tab_waivers, tab_ranks, tab_status = st.tabs(
        [
            "Roster",
            "Standings",
            "Matchups",
            "Positional grades",
            "Trade targets",
            "Waiver pickups",
            "Consensus ranks",
            "Source status",
        ]
    )

    with tab_roster:
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

    with tab_standings:
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

    with tab_matchups:
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

    with tab_grades:
        st.markdown(
            "Grades blend FantasyPros + Sleeper consensus ranks vs positional replacement level. "
            "If rankings are unavailable, depth-only grades are shown."
        )
        if not team_names:
            st.info("Pick a team after data loads.")
        else:
            grade_team = st.selectbox("Grade team", team_names, index=default_idx, key="grade_team")
            grades = grade_roster(grade_team, rosters, players, consensus_for_grade)
            if not grades:
                st.info("No positional grades for this team.")
            else:
                # Compact summary — long "why" text is clipped in st.dataframe cells,
                # so full explanations render below as wrapped markdown.
                summary = pd.DataFrame(
                    [
                        {
                            "Pos": g["position"],
                            "Grade": g["grade"],
                            "Count": g["count"],
                            "Best rank": g.get("best_rank") if g.get("best_rank") is not None else "—",
                            "Players": g["players"],
                        }
                        for g in grades
                    ]
                )
                st.dataframe(summary, use_container_width=True, hide_index=True)
                st.markdown("##### Why")
                for g in grades:
                    why = (g.get("why") or "").strip() or "—"
                    st.markdown(f"**{g['position']} — {g['grade']}.** {why}")

    with tab_trades:
        st.markdown(
            "Targets on other rosters who upgrade your weak (or average) positions, "
            "preferring managers with positional surplus. Grounded in consensus ranks."
        )
        if not team_names:
            st.info("Pick a team after data loads.")
        elif not consensus_for_grade:
            st.warning("No consensus rankings yet — refresh data or check Source status.")
        else:
            trade_team = st.selectbox(
                "Your team", team_names, index=default_idx, key="trade_team"
            )
            trades = find_trade_targets(
                trade_team, rosters, players, consensus_for_grade, limit=12
            )
            if not trades:
                st.info(
                    "No clear trade upgrades found. Your weak spots may already be "
                    "competitive, or counterparts lack ranked surplus."
                )
            else:
                summary = pd.DataFrame(
                    [
                        {
                            "Player": t["player"],
                            "Pos": t["position"],
                            "Owner": t["owner"],
                            "Rank": t["rank"],
                            "Your best": (
                                f"{t['your_best']} #{t['your_best_rank']}"
                                if t.get("your_best_rank") is not None
                                else "—"
                            ),
                            "Owner depth": t["owner_depth"],
                            "Offer hint": t.get("offer_hint") or "—",
                        }
                        for t in trades
                    ]
                )
                # Wide Offer hint + taller rows so long cells are reachable via
                # horizontal/vertical dataframe scroll (not clipped mid-sentence).
                st.dataframe(
                    summary,
                    hide_index=True,
                    width="stretch",
                    height=min(420, 56 + 68 * max(len(summary), 1)),
                    row_height=68,
                    column_config={
                        "Player": st.column_config.Column(width="medium"),
                        "Pos": st.column_config.Column(width="small"),
                        "Owner": st.column_config.Column(width="medium"),
                        "Rank": st.column_config.NumberColumn(width="small"),
                        "Your best": st.column_config.Column(width="medium"),
                        "Owner depth": st.column_config.NumberColumn(width="small"),
                        "Offer hint": st.column_config.TextColumn(
                            "Offer hint",
                            width=560,
                            help="Suggested surplus piece to offer — scroll sideways if truncated.",
                        ),
                    },
                )
                st.markdown("##### Why")
                for t in trades:
                    why = (t.get("why") or "").strip() or "—"
                    st.markdown(
                        f"**{t['player']} ({t['position']}) — {t['owner']}.** {why}"
                    )

    with tab_waivers:
        st.markdown(
            "Free agents who help weak/average positions, ranked by consensus. "
            "Sleeper trending adds get a boost. Explicit ESPN/demo FA pool is merged "
            "with unrostered consensus names."
        )
        if not team_names:
            st.info("Pick a team after data loads.")
        elif not consensus_for_grade:
            st.warning("No consensus rankings yet — refresh data or check Source status.")
        else:
            waiver_team = st.selectbox(
                "Your team", team_names, index=default_idx, key="waiver_team"
            )
            pickups = find_waiver_pickups(
                waiver_team,
                rosters,
                players,
                consensus_for_grade,
                free_agents=free_agents,
                trending_names=trending,
                limit=15,
            )
            if trending:
                st.caption(
                    "Sleeper trending: "
                    + ", ".join(trending[:12])
                    + ("…" if len(trending) > 12 else "")
                )
            if not pickups:
                st.info(
                    "No ranked free-agent upgrades for your weak spots right now. "
                    "Try Refresh Data after waivers process."
                )
            else:
                summary = pd.DataFrame(
                    [
                        {
                            "Player": p["player"],
                            "Pos": p["position"],
                            "NFL": p.get("nfl_team") or "—",
                            "Rank": p["rank"],
                            "Your best": (
                                f"{p['your_best']} #{p['your_best_rank']}"
                                if p.get("your_best_rank") is not None
                                else "—"
                            ),
                            "Trending": "Yes" if p.get("trending") else "—",
                        }
                        for p in pickups
                    ]
                )
                st.dataframe(summary, use_container_width=True, hide_index=True)
                st.markdown("##### Why")
                for p in pickups:
                    why = (p.get("why") or "").strip() or "—"
                    st.markdown(f"**{p['player']} ({p['position']}).** {why}")

    with tab_ranks:
        st.markdown("Consensus board (FantasyPros weighted with Sleeper search ranks).")
        if not consensus_table:
            st.info("No consensus rankings in the latest refresh — check Source status.")
        else:
            cdf = pd.DataFrame(consensus_table)
            positions = sorted({r["Pos"] for r in consensus_table if r["Pos"] != "—"})
            default_pos = [p for p in ["QB", "RB", "WR", "TE", "DST", "K"] if p in positions] or positions
            pos_filter = st.multiselect("Positions", positions, default=default_pos)
            if pos_filter:
                cdf = cdf[cdf["Pos"].isin(pos_filter)]
            st.dataframe(cdf.sort_values(["Pos", "Rank"]), use_container_width=True, hide_index=True)

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

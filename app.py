from __future__ import annotations

import importlib
import json
import re
import sys
from datetime import datetime, timezone
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
from analysis.llm_client import describe_setup, retry_settings
from analysis.llm_context import (
    build_recommendation_context,
    context_format,
    encode_toon,
    estimate_size,
    pack_context_for_llm,
)

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


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "team").strip())
    return cleaned.strip("-")[:48] or "team"


def _build_export_pack(
    *,
    team_name: str,
    hunt_positions: list[str],
    meta,
    rosters,
    players,
    standings,
    rankings,
    free_agents,
    news_items,
    include_start_sit: bool,
) -> dict:
    """Build full + packed LLM context for download/copy without calling Gemini."""
    context = build_recommendation_context(
        team_name=team_name,
        hunt_positions=hunt_positions,
        meta=meta,
        rosters=rosters,
        players=players,
        standings=standings,
        rankings=rankings,
        free_agents=free_agents,
        news_items=news_items,
        include_start_sit=include_start_sit,
    )
    context_sent = pack_context_for_llm(context)
    wire = context_format()
    size_stats = estimate_size(context_sent)
    return {
        "context": context,
        "context_sent": context_sent,
        "context_toon": size_stats.get("toon") or "",
        "size_stats": {
            k: size_stats[k] for k in size_stats if k not in ("json_compact", "toon")
        },
        "wire_format": wire,
        "raw_response": None,
        "result": None,
        "ok": None,
        "error": None,
    }


def _llm_export_bundle(out: dict, *, team_name: str, week: int | str) -> dict[str, str]:
    """Build downloadable export blobs + filenames for JSON/TOON/raw."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"fantasy-llm-{_safe_filename(team_name)}-wk{week}-{stamp}"
    context_json = json.dumps(out.get("context") or {}, indent=2, default=str)
    context_toon = out.get("context_toon") or ""
    if not context_toon and out.get("context_sent"):
        try:
            context_toon = encode_toon(out.get("context_sent") or {})
        except Exception:  # noqa: BLE001
            context_toon = ""
    raw_payload = {
        "raw_response": out.get("raw_response"),
        "result": out.get("result"),
        "ok": out.get("ok"),
        "error": out.get("error"),
        "wire_format": out.get("wire_format"),
        "size_stats": out.get("size_stats"),
        "context_sent": out.get("context_sent"),
    }
    raw_json = json.dumps(raw_payload, indent=2, default=str)
    return {
        "context_json": context_json,
        "context_toon": context_toon,
        "raw_json": raw_json,
        "ctx_json_name": f"{base}-context.json",
        "ctx_toon_name": f"{base}-context.toon",
        "raw_name": f"{base}-raw.json",
    }


def main() -> None:
    st.title("FantasyAnalysis")
    st.caption(
        "ESPN league + fused weekly/ROS ranks + news → Gemini trade & waiver ideas."
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
            "LLM recommendations/export",
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
            "**Fused** weekly / ROS boards (default **RRF** over FantasyPros + Sleeper "
            "+ ESPN proj when present). Per-source boards stay in SQLite — expand below."
        )
        horizon = st.radio(
            "Horizon",
            ["ros", "weekly"],
            horizontal=True,
            format_func=lambda x: "ROS" if x == "ros" else "Weekly",
        )
        fused = _rank_table(ranking_rows, horizon=horizon, source_filter="consensus")
        if fused.empty:
            st.info("No fused rankings for this horizon — try Refresh Data.")
        else:
            positions = sorted({p for p in fused["Pos"].tolist() if p != "—"})
            default_pos = [p for p in ["QB", "RB", "WR", "TE", "DST", "K"] if p in positions] or positions
            pos_filter = st.multiselect("Positions", positions, default=default_pos, key="rank_pos")
            view = fused
            if pos_filter:
                view = fused[fused["Pos"].isin(pos_filter)]
            st.dataframe(
                view.sort_values(["Pos", "Rank"]),
                use_container_width=True,
                hide_index=True,
            )
        with st.expander("Per-source boards (detail)"):
            source = st.selectbox(
                "Source",
                ["fantasypros", "fantasypros_mock", "sleeper", "espn", "all"],
                index=0,
                key="rank_src_detail",
            )
            if source == "all":
                detail = _rank_table(ranking_rows, horizon=horizon)
                detail = detail[detail["Source"] != "consensus"] if not detail.empty else detail
            else:
                detail = _rank_table(ranking_rows, horizon=horizon, source_filter=source)
            if detail.empty:
                st.caption("No rows for that source/horizon.")
            else:
                st.dataframe(
                    detail.sort_values(["Pos", "Rank", "Source"]),
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
            "Export fused league context anytime for Claude-in-browser, or generate "
            "recommendations with **Google Gemini**. Context uses fused weekly + ROS "
            "skill ranks (no raw multi-source dumps). **Never recommends QB/DST/K trades.**"
        )
        if not team_names:
            st.info("Load league data first.")
        else:
            rec_team = st.selectbox("Your team", team_names, index=default_idx, key="rec_team")
            hunt = st.multiselect(
                "Hunt positions (passed to LLM / export)",
                options=list(HUNT_POS_OPTIONS),
                default=list(DEFAULT_HUNT_POS),
                key="rec_hunt",
            )
            include_ss = st.checkbox("Include start/sit", value=True)

            week = getattr(meta, "current_week", "?") if meta else "?"
            export_pack = _build_export_pack(
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
            # Live pack always drives JSON/TOON download (matches current UI controls).
            # Attach last generate's raw response when present.
            out = st.session_state.get("llm_recs")
            export_src = {
                **export_pack,
                "raw_response": (out or {}).get("raw_response"),
                "result": (out or {}).get("result"),
                "ok": (out or {}).get("ok"),
                "error": (out or {}).get("error"),
            }

            bundle = _llm_export_bundle(export_src, team_name=rec_team, week=week)
            stats = export_src.get("size_stats") or {}
            wire = export_src.get("wire_format") or "toon"

            st.subheader("Export for Claude / paste")
            st.caption(
                f"Packed **{wire.upper()}** context (fused skill ranks RB/WR/TE/QB; "
                "DST/K + raw multi-source dumps omitted). No Gemini call required. "
                f"≈ JSON {stats.get('json_chars', '?')} chars "
                f"(~{stats.get('json_tokens_est', '?')} tok) vs TOON {stats.get('toon_chars', '?')} chars "
                f"(~{stats.get('toon_tokens_est', '?')} tok; "
                f"{stats.get('token_savings_pct_est', '?')}% fewer est. tokens)."
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                st.download_button(
                    "Download full context JSON",
                    data=bundle["context_json"],
                    file_name=bundle["ctx_json_name"],
                    mime="application/json",
                    use_container_width=True,
                    key="dl_llm_context",
                )
            with c2:
                st.download_button(
                    "Download packed TOON",
                    data=bundle["context_toon"],
                    file_name=bundle["ctx_toon_name"],
                    mime="text/plain",
                    use_container_width=True,
                    key="dl_llm_context_toon",
                    disabled=not bool(bundle["context_toon"]),
                )
            with c3:
                st.download_button(
                    "Download raw LLM response",
                    data=bundle["raw_json"],
                    file_name=bundle["raw_name"],
                    mime="application/json",
                    use_container_width=True,
                    key="dl_llm_raw",
                    disabled=not bool(export_src.get("raw_response") or export_src.get("result")),
                )

            with st.expander("Full context JSON (copy/paste)", expanded=False):
                st.text_area(
                    "context",
                    value=bundle["context_json"],
                    height=280,
                    label_visibility="collapsed",
                    key="llm_context_textarea",
                )
                st.caption(
                    f"Filename suggestion: `{bundle['ctx_json_name']}` · "
                    f"{len(bundle['context_json']):,} chars"
                )
            with st.expander(f"Packed context ({wire})"):
                if wire == "toon" and bundle["context_toon"]:
                    st.code(bundle["context_toon"], language="text")
                    st.caption(f"{len(bundle['context_toon']):,} chars TOON")
                else:
                    sent = json.dumps(export_src.get("context_sent") or {}, indent=2, default=str)
                    st.code(sent, language="json")
                    st.caption(f"{len(sent):,} chars (packed JSON)")

            st.divider()
            st.subheader("Generate with Gemini")
            _retry_max, _retry_base = retry_settings()
            st.caption(
                f"{describe_setup()} Auto-retries on high demand "
                f"(starts at {_retry_base:g}s, doubles each try; up to {_retry_max} attempts)."
            )
            if st.button("Generate recommendations", type="primary"):
                with st.spinner("Calling Gemini… (retries with backoff if busy)"):
                    gen_out = generate_recommendations(
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
                st.session_state["llm_recs"] = gen_out
                st.rerun()

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
                elif out.get("ok") is False:
                    st.error(out.get("error") or "LLM unavailable")
                    st.markdown(f"**Setup:** {out.get('setup') or describe_setup()}")
                    st.caption(
                        "Export above still works without Gemini — "
                        "paste JSON into Claude in the browser."
                    )
                if st.button("Clear LLM results", use_container_width=False, key="clear_llm"):
                    st.session_state.pop("llm_recs", None)
                    st.rerun()
                if out.get("raw_response"):
                    with st.expander("Raw LLM response"):
                        st.code(str(out.get("raw_response")), language="json")

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

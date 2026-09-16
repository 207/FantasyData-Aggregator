from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session, SQLModel, create_engine, select

from storage.models import (
    LeagueMeta,
    MatchupRow,
    Player,
    Ranking,
    RefreshLog,
    RosterSnapshot,
    TeamStanding,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "fantasy.db"


def get_engine(db_path: Path | None = None):
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False)


def init_db(engine=None) -> None:
    engine = engine or get_engine()
    SQLModel.metadata.create_all(engine)
    _ensure_ranking_columns(engine)


def _ensure_ranking_columns(engine) -> None:
    """SQLite create_all won't add new columns — patch rankings if needed."""
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(rankings)").fetchall()
        if not rows:
            return
        cols = {r[1] for r in rows}
        if "player_name" not in cols:
            conn.exec_driver_sql("ALTER TABLE rankings ADD COLUMN player_name VARCHAR DEFAULT ''")
        if "position" not in cols:
            conn.exec_driver_sql("ALTER TABLE rankings ADD COLUMN position VARCHAR DEFAULT ''")
        conn.commit()


def clear_league_tables(session: Session) -> None:
    """Clear league snapshot tables. Rankings are replaced separately."""
    for model in (RosterSnapshot, TeamStanding, MatchupRow, Player, LeagueMeta, RefreshLog):
        for row in session.exec(select(model)).all():
            session.delete(row)
    session.commit()


def clear_rankings(session: Session) -> None:
    for row in session.exec(select(Ranking)).all():
        session.delete(row)
    session.commit()


def upsert_league_snapshot(payload: dict[str, Any], engine=None) -> LeagueMeta:
    """Replace current league snapshot with a freshly pulled payload."""
    engine = engine or get_engine()
    init_db(engine)

    with Session(engine) as session:
        clear_league_tables(session)

        meta = LeagueMeta(
            league_id=str(payload["league_id"]),
            league_name=payload.get("league_name", ""),
            year=int(payload["year"]),
            current_week=int(payload.get("current_week", 1)),
            scoring_settings=json.dumps(payload.get("scoring_settings", {})),
            roster_slots=json.dumps(payload.get("roster_slots", {})),
            team_names=json.dumps(payload.get("team_names", [])),
            source_mode=payload.get("source_mode", "demo"),
            refreshed_at=datetime.now(timezone.utc),
        )
        session.add(meta)

        for p in payload.get("players", []):
            session.add(
                Player(
                    player_id=str(p["player_id"]),
                    name=p["name"],
                    position=p.get("position", ""),
                    nfl_team=p.get("nfl_team", ""),
                )
            )

        for r in payload.get("rosters", []):
            session.add(
                RosterSnapshot(
                    team_id=str(r["team_id"]),
                    team_name=r["team_name"],
                    player_id=str(r["player_id"]),
                    week=int(r.get("week", meta.current_week)),
                    slot=r.get("slot", "bench"),
                    lineup_slot=r.get("lineup_slot", ""),
                )
            )

        for s in payload.get("standings", []):
            session.add(
                TeamStanding(
                    team_id=str(s["team_id"]),
                    team_name=s["team_name"],
                    wins=int(s.get("wins", 0)),
                    losses=int(s.get("losses", 0)),
                    ties=int(s.get("ties", 0)),
                    points_for=float(s.get("points_for", 0)),
                    points_against=float(s.get("points_against", 0)),
                    week=int(s.get("week", meta.current_week)),
                )
            )

        for m in payload.get("matchups", []):
            session.add(
                MatchupRow(
                    week=int(m.get("week", meta.current_week)),
                    home_team_id=str(m["home_team_id"]),
                    home_team_name=m["home_team_name"],
                    home_score=float(m.get("home_score", 0)),
                    away_team_id=str(m["away_team_id"]),
                    away_team_name=m["away_team_name"],
                    away_score=float(m.get("away_score", 0)),
                )
            )

        for log in payload.get("refresh_logs", []):
            session.add(
                RefreshLog(
                    source=log.get("source", "unknown"),
                    status=log.get("status", "ok"),
                    message=log.get("message", ""),
                )
            )

        # Optional rankings bundled on the same refresh payload
        if payload.get("rankings") is not None:
            clear_rankings(session)
            for row in payload.get("rankings", []):
                session.add(
                    Ranking(
                        player_id=str(row.get("player_id") or row.get("name") or ""),
                        player_name=str(row.get("name") or row.get("player_name") or ""),
                        position=str(row.get("position") or ""),
                        source=str(row.get("source", "consensus")),
                        week=int(row.get("week", meta.current_week)),
                        rank=int(row.get("rank", 999)),
                        tier=row.get("tier"),
                        projected_points=row.get("projected_points"),
                        pulled_at=row.get("pulled_at") or datetime.now(timezone.utc),
                    )
                )

        session.commit()
        session.refresh(meta)
        return meta


def load_dashboard(engine=None) -> dict[str, Any]:
    engine = engine or get_engine()
    init_db(engine)

    with Session(engine) as session:
        meta = session.exec(select(LeagueMeta).order_by(LeagueMeta.id.desc())).first()
        if not meta:
            return {"meta": None}

        players = {p.player_id: p for p in session.exec(select(Player)).all()}
        rosters = session.exec(select(RosterSnapshot)).all()
        standings = session.exec(select(TeamStanding)).all()
        matchups = session.exec(select(MatchupRow)).all()
        logs = session.exec(select(RefreshLog).order_by(RefreshLog.id.desc())).all()
        rankings = session.exec(select(Ranking)).all()

        return {
            "meta": meta,
            "players": players,
            "rosters": rosters,
            "standings": standings,
            "matchups": matchups,
            "logs": logs,
            "rankings": rankings,
        }

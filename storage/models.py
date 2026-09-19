from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Player(SQLModel, table=True):
    __tablename__ = "players"
    # Streamlit reloads re-exec models; allow redefine on the shared MetaData.
    __table_args__ = {"extend_existing": True}

    player_id: str = Field(primary_key=True)
    name: str
    position: str
    nfl_team: str = ""


class Ranking(SQLModel, table=True):
    __tablename__ = "rankings"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: str = Field(index=True)
    player_name: str = ""
    position: str = ""
    source: str
    horizon: str = "ros"  # ros | weekly
    week: int
    rank: int
    tier: Optional[int] = None
    projected_points: Optional[float] = None
    pulled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NewsItem(SQLModel, table=True):
    __tablename__ = "news"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: str = Field(index=True)
    player_name: str = ""
    source: str
    headline: str
    body: str = ""
    injury_flag: str = ""
    published_at: Optional[datetime] = None


class RosterSnapshot(SQLModel, table=True):
    __tablename__ = "roster_snapshots"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: str = Field(index=True)
    team_name: str
    player_id: str = Field(index=True)
    week: int
    slot: str  # starter | bench | IR
    lineup_slot: str = ""  # QB, RB, WR, TE, FLEX, etc.


class TeamStanding(SQLModel, table=True):
    __tablename__ = "team_standings"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: str = Field(index=True)
    team_name: str
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    week: int = 0


class MatchupRow(SQLModel, table=True):
    __tablename__ = "matchups"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    week: int
    home_team_id: str
    home_team_name: str
    home_score: float = 0.0
    away_team_id: str
    away_team_name: str
    away_score: float = 0.0


class LeagueMeta(SQLModel, table=True):
    __tablename__ = "league_meta"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    league_id: str
    league_name: str = ""
    year: int
    current_week: int = 1
    scoring_settings: str = ""
    roster_slots: str = ""
    team_names: str = ""
    source_mode: str = "demo"  # demo | espn
    free_agents_json: str = "[]"
    trending_json: str = "[]"
    refreshed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RefreshLog(SQLModel, table=True):
    __tablename__ = "refresh_log"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    source: str
    status: str  # ok | error | stale
    message: str = ""
    pulled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

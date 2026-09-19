from __future__ import annotations

"""Demo league payload used when ESPN credentials are missing or ESPN fails."""

DEMO_PAYLOAD = {
    "league_id": "demo-1001",
    "league_name": "Demo Gridiron League",
    "year": 2026,
    "current_week": 3,
    "source_mode": "demo",
    "scoring_settings": {"ppr": True, "passing_td": 4, "reception": 1.0},
    "roster_slots": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1, "BE": 6},
    "team_names": [
        "Midnight Express",
        "Gridiron Ghosts",
        "Red Zone Renegades",
        "Pocket Passers",
        "Blitz Brigade",
        "End Zone Elite",
        "Hail Mary FC",
        "Touchdown Titans",
        "First Down Force",
        "Sunday Scramble",
    ],
    "players": [
        {"player_id": "p1", "name": "Josh Allen", "position": "QB", "nfl_team": "BUF"},
        {"player_id": "p2", "name": "Christian McCaffrey", "position": "RB", "nfl_team": "SF"},
        {"player_id": "p3", "name": "Breece Hall", "position": "RB", "nfl_team": "NYJ"},
        {"player_id": "p4", "name": "CeeDee Lamb", "position": "WR", "nfl_team": "DAL"},
        {"player_id": "p5", "name": "Amon-Ra St. Brown", "position": "WR", "nfl_team": "DET"},
        {"player_id": "p6", "name": "Travis Kelce", "position": "TE", "nfl_team": "KC"},
        {"player_id": "p7", "name": "Ja'Marr Chase", "position": "WR", "nfl_team": "CIN"},
        {"player_id": "p8", "name": "Bills D/ST", "position": "DST", "nfl_team": "BUF"},
        {"player_id": "p9", "name": "Justin Tucker", "position": "K", "nfl_team": "BAL"},
        {"player_id": "p10", "name": "James Cook", "position": "RB", "nfl_team": "BUF"},
        {"player_id": "p11", "name": "DK Metcalf", "position": "WR", "nfl_team": "SEA"},
        {"player_id": "p12", "name": "Tua Tagovailoa", "position": "QB", "nfl_team": "MIA"},
        {"player_id": "p13", "name": "Saquon Barkley", "position": "RB", "nfl_team": "PHI"},
        {"player_id": "p14", "name": "Jahmyr Gibbs", "position": "RB", "nfl_team": "DET"},
        {"player_id": "p15", "name": "Tyreek Hill", "position": "WR", "nfl_team": "MIA"},
        {"player_id": "p16", "name": "A.J. Brown", "position": "WR", "nfl_team": "PHI"},
        {"player_id": "p17", "name": "Mark Andrews", "position": "TE", "nfl_team": "BAL"},
        {"player_id": "p18", "name": "Puka Nacua", "position": "WR", "nfl_team": "LAR"},
        {"player_id": "p19", "name": "49ers D/ST", "position": "DST", "nfl_team": "SF"},
        {"player_id": "p20", "name": "Harrison Butker", "position": "K", "nfl_team": "KC"},
        {"player_id": "p21", "name": "Patrick Mahomes", "position": "QB", "nfl_team": "KC"},
        {"player_id": "p22", "name": "Bijan Robinson", "position": "RB", "nfl_team": "ATL"},
        {"player_id": "p23", "name": "Kyren Williams", "position": "RB", "nfl_team": "LAR"},
        {"player_id": "p24", "name": "Justin Jefferson", "position": "WR", "nfl_team": "MIN"},
        {"player_id": "p25", "name": "Nico Collins", "position": "WR", "nfl_team": "HOU"},
        {"player_id": "p26", "name": "Sam LaPorta", "position": "TE", "nfl_team": "DET"},
        {"player_id": "p27", "name": "DeVonta Smith", "position": "WR", "nfl_team": "PHI"},
        {"player_id": "p28", "name": "Ravens D/ST", "position": "DST", "nfl_team": "BAL"},
        {"player_id": "p29", "name": "Brandon Aubrey", "position": "K", "nfl_team": "DAL"},
        {"player_id": "p30", "name": "Jalen Hurts", "position": "QB", "nfl_team": "PHI"},
        {"player_id": "p31", "name": "Derrick Henry", "position": "RB", "nfl_team": "BAL"},
        {"player_id": "p32", "name": "Jonathan Taylor", "position": "RB", "nfl_team": "IND"},
        {"player_id": "p33", "name": "Brandon Aiyuk", "position": "WR", "nfl_team": "SF"},
        {"player_id": "p34", "name": "Mike Evans", "position": "WR", "nfl_team": "TB"},
        {"player_id": "p35", "name": "Trey McBride", "position": "TE", "nfl_team": "ARI"},
        {"player_id": "p36", "name": "Garrett Wilson", "position": "WR", "nfl_team": "NYJ"},
        {"player_id": "p37", "name": "Cowboys D/ST", "position": "DST", "nfl_team": "DAL"},
        {"player_id": "p38", "name": "Jake Elliott", "position": "K", "nfl_team": "PHI"},
        {"player_id": "p39", "name": "Lamar Jackson", "position": "QB", "nfl_team": "BAL"},
        {"player_id": "p40", "name": "Joe Mixon", "position": "RB", "nfl_team": "HOU"},
        # Free agents (not assigned to any roster below)
        {"player_id": "fa1", "name": "Isiah Pacheco", "position": "RB", "nfl_team": "KC"},
        {"player_id": "fa2", "name": "Zack Moss", "position": "RB", "nfl_team": "CIN"},
        {"player_id": "fa3", "name": "Courtland Sutton", "position": "WR", "nfl_team": "DEN"},
        {"player_id": "fa4", "name": "Christian Kirk", "position": "WR", "nfl_team": "HOU"},
        {"player_id": "fa5", "name": "Dallas Goedert", "position": "TE", "nfl_team": "PHI"},
        {"player_id": "fa6", "name": "Baker Mayfield", "position": "QB", "nfl_team": "TB"},
        {"player_id": "fa7", "name": "Steelers D/ST", "position": "DST", "nfl_team": "PIT"},
        {"player_id": "fa8", "name": "Cairo Santos", "position": "K", "nfl_team": "CHI"},
        {"player_id": "fa9", "name": "Jaylen Warren", "position": "RB", "nfl_team": "PIT"},
        {"player_id": "fa10", "name": "Rome Odunze", "position": "WR", "nfl_team": "CHI"},
    ],
    "free_agents": [
        {"player_id": "fa1", "name": "Isiah Pacheco", "position": "RB", "nfl_team": "KC"},
        {"player_id": "fa2", "name": "Zack Moss", "position": "RB", "nfl_team": "CIN"},
        {"player_id": "fa3", "name": "Courtland Sutton", "position": "WR", "nfl_team": "DEN"},
        {"player_id": "fa4", "name": "Christian Kirk", "position": "WR", "nfl_team": "HOU"},
        {"player_id": "fa5", "name": "Dallas Goedert", "position": "TE", "nfl_team": "PHI"},
        {"player_id": "fa6", "name": "Baker Mayfield", "position": "QB", "nfl_team": "TB"},
        {"player_id": "fa7", "name": "Steelers D/ST", "position": "DST", "nfl_team": "PIT"},
        {"player_id": "fa8", "name": "Cairo Santos", "position": "K", "nfl_team": "CHI"},
        {"player_id": "fa9", "name": "Jaylen Warren", "position": "RB", "nfl_team": "PIT"},
        {"player_id": "fa10", "name": "Rome Odunze", "position": "WR", "nfl_team": "CHI"},
    ],
    "rosters": [],
    "standings": [],
    "matchups": [],
    "refresh_logs": [
        {
            "source": "espn",
            "status": "stale",
            "message": "Running in demo mode — add LEAGUE_ID, SWID, and ESPN_S2 to config/.env for live data.",
        },
        {"source": "demo", "status": "ok", "message": "Loaded sample 10-team PPR league for week 3."},
        {
            "source": "espn_free_agents",
            "status": "ok",
            "message": "Demo free-agent pool with 10 available players.",
        },
    ],
}


def _assign_lineup(players_chunk: list[dict]) -> list[tuple[dict, str, str]]:
    """Map players to lineup slots that match their positions (starter vs bench)."""
    needs = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "DST": 1, "K": 1}
    filled = {pos: 0 for pos in needs}
    flex_left = 1
    assigned: list[tuple[dict, str, str]] = []

    for player in players_chunk:
        pos = player["position"]
        if pos in needs and filled[pos] < needs[pos]:
            filled[pos] += 1
            assigned.append((player, "starter", pos))
        elif pos in {"RB", "WR", "TE"} and flex_left > 0:
            flex_left -= 1
            assigned.append((player, "starter", "FLEX"))
        else:
            assigned.append((player, "bench", "BE"))
    return assigned


def build_demo_payload() -> dict:
    """Expand compact demo into full roster/standings/matchup snapshot."""
    payload = {
        **DEMO_PAYLOAD,
        "rosters": [],
        "standings": [],
        "matchups": [],
        "free_agents": list(DEMO_PAYLOAD.get("free_agents") or []),
    }
    teams = payload["team_names"]
    players = payload["players"]

    # First 5 teams get 8-player chunks with position-correct lineup slots.
    for ti, team in enumerate(teams[:5]):
        team_id = f"t{ti + 1}"
        chunk = players[ti * 8 : (ti + 1) * 8]
        for player, slot, lineup in _assign_lineup(chunk):
            payload["rosters"].append(
                {
                    "team_id": team_id,
                    "team_name": team,
                    "player_id": player["player_id"],
                    "week": payload["current_week"],
                    "slot": slot,
                    "lineup_slot": lineup,
                }
            )

    records = [
        (3, 0, 312.4, 248.1),
        (2, 1, 298.7, 271.0),
        (2, 1, 285.2, 279.4),
        (1, 2, 261.8, 290.5),
        (1, 2, 254.1, 301.2),
        (2, 1, 277.0, 266.3),
        (0, 3, 231.5, 318.9),
        (1, 2, 249.6, 288.0),
        (2, 1, 270.3, 255.7),
        (1, 2, 242.0, 274.8),
    ]
    for i, team in enumerate(teams):
        w, l, pf, pa = records[i]
        payload["standings"].append(
            {
                "team_id": f"t{i + 1}",
                "team_name": team,
                "wins": w,
                "losses": l,
                "ties": 0,
                "points_for": pf,
                "points_against": pa,
                "week": payload["current_week"],
            }
        )

    pairs = [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)]
    scores = [(118.4, 102.1), (95.6, 110.2), (88.0, 91.5), (104.3, 97.8), (112.7, 106.0)]
    for (hi, ai), (hs, aws) in zip(pairs, scores):
        payload["matchups"].append(
            {
                "week": payload["current_week"],
                "home_team_id": f"t{hi + 1}",
                "home_team_name": teams[hi],
                "home_score": hs,
                "away_team_id": f"t{ai + 1}",
                "away_team_name": teams[ai],
                "away_score": aws,
            }
        )

    return payload

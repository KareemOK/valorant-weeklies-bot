"""
SQLite data layer for the Valorant Weeklies bot.

Everything (the Discord bot and the companion leaderboard web page) reads
and writes this same file, so no separate database server is needed.
"""

import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "weeklies.db"))

# Screenshots are kept next to the database file (so they live on the same
# mounted volume and survive container restarts/redeploys) rather than
# inside the container's throwaway filesystem.
SCREENSHOTS_DIR = DB_PATH.parent / "screenshots"

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    discord_id      TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    riot_name       TEXT,              -- e.g. "Sova#EU1", set via /link
    elo             REAL NOT NULL DEFAULT 1000,
    wins            INTEGER NOT NULL DEFAULT 0,
    losses          INTEGER NOT NULL DEFAULT 0,
    kills           INTEGER NOT NULL DEFAULT 0,
    deaths          INTEGER NOT NULL DEFAULT 0,
    assists         INTEGER NOT NULL DEFAULT 0,
    games_played    INTEGER NOT NULL DEFAULT 0,
    created_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at       REAL NOT NULL,
    reported_by     TEXT NOT NULL,      -- discord_id of whoever ran /report-match
    winner          TEXT NOT NULL,      -- 'team1' | 'team2' | 'draw'
    map_name        TEXT,
    team1_score     INTEGER,
    team2_score     INTEGER,
    screenshot_path TEXT,               -- filename under SCREENSHOTS_DIR, if kept
    screenshot_note TEXT,               -- optional free-text note
    confirmed       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS match_players (
    match_id        INTEGER NOT NULL REFERENCES matches(id),
    discord_id      TEXT NOT NULL REFERENCES players(discord_id),
    team            TEXT NOT NULL,      -- 'team1' | 'team2'
    agent           TEXT,
    kills           INTEGER NOT NULL DEFAULT 0,
    deaths          INTEGER NOT NULL DEFAULT 0,
    assists         INTEGER NOT NULL DEFAULT 0,
    acs             INTEGER,
    first_bloods    INTEGER NOT NULL DEFAULT 0,
    plants          INTEGER NOT NULL DEFAULT 0,
    defuses         INTEGER NOT NULL DEFAULT 0,
    econ_rating     INTEGER,
    elo_before      REAL,
    elo_after       REAL,
    PRIMARY KEY (match_id, discord_id)
);
"""

# Columns added after the initial release. Listed here (rather than just in
# SCHEMA) so an existing weeklies.db from an earlier version of this project
# gets upgraded in place -- CREATE TABLE IF NOT EXISTS alone won't add new
# columns to a table that already exists.
_MIGRATIONS = {
    "matches": {
        "team1_score": "INTEGER",
        "team2_score": "INTEGER",
        "screenshot_path": "TEXT",
    },
    "match_players": {
        "acs": "INTEGER",
        "first_bloods": "INTEGER NOT NULL DEFAULT 0",
        "plants": "INTEGER NOT NULL DEFAULT 0",
        "defuses": "INTEGER NOT NULL DEFAULT 0",
        "econ_rating": "INTEGER",
    },
}


def _run_migrations(conn):
    for table, columns in _MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for col_name, col_type in columns.items():
            if col_name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _run_migrations(conn)


def upsert_player(discord_id: str, display_name: str, riot_name: str | None = None):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT discord_id FROM players WHERE discord_id = ?", (discord_id,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO players (discord_id, display_name, riot_name, created_at) "
                "VALUES (?, ?, ?, ?)",
                (discord_id, display_name, riot_name, time.time()),
            )
        else:
            if riot_name is not None:
                conn.execute(
                    "UPDATE players SET display_name = ?, riot_name = ? WHERE discord_id = ?",
                    (display_name, riot_name, discord_id),
                )
            else:
                conn.execute(
                    "UPDATE players SET display_name = ? WHERE discord_id = ?",
                    (display_name, discord_id),
                )


def get_player(discord_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM players WHERE discord_id = ?", (discord_id,)
        ).fetchone()


def _strip_clan_tag(name: str) -> str:
    """
    Valorant lets players set a clan tag that displays in-game as
    "TAG | ActualName" -- that prefix is purely cosmetic and has nothing to
    do with their Riot ID, so it needs to come off before matching a name
    read off a scoreboard against what someone /link'd.
    """
    return re.sub(r"^\S+\s*\|\s*", "", name).strip()


def find_player_by_riot_name(riot_name: str) -> sqlite3.Row | None:
    """
    Best-effort match, tried in order: exact match on the raw string, exact
    match with any clan tag prefix stripped, then a case-insensitive
    starts-with match on the name portion before '#'.
    """
    with get_conn() as conn:
        exact = conn.execute(
            "SELECT * FROM players WHERE riot_name = ? COLLATE NOCASE", (riot_name,)
        ).fetchone()
        if exact:
            return exact

        stripped = _strip_clan_tag(riot_name)
        if stripped != riot_name:
            exact_stripped = conn.execute(
                "SELECT * FROM players WHERE riot_name = ? COLLATE NOCASE", (stripped,)
            ).fetchone()
            if exact_stripped:
                return exact_stripped

        name_part = stripped.split("#")[0]
        return conn.execute(
            "SELECT * FROM players WHERE riot_name LIKE ? COLLATE NOCASE",
            (f"{name_part}%",),
        ).fetchone()


def get_leaderboard(limit: int = 25):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT display_name, riot_name, elo, wins, losses, kills, deaths,
                   assists, games_played
            FROM players
            WHERE games_played > 0
            ORDER BY elo DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_leaderboard_extended(limit: int = 50):
    """
    Season aggregates computed straight from match_players/matches (rather
    than more running-total columns bolted onto players), for the
    sortable web leaderboard: adds KPR, ACS average, plants, defuses,
    first bloods and win rate on top of the basics.
    """
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT
                p.discord_id,
                p.display_name,
                p.riot_name,
                p.elo,
                p.wins,
                p.losses,
                p.games_played,
                SUM(mp.kills)                                    AS kills,
                SUM(mp.deaths)                                   AS deaths,
                SUM(mp.assists)                                  AS assists,
                SUM(mp.plants)                                   AS plants,
                SUM(mp.defuses)                                  AS defuses,
                SUM(mp.first_bloods)                             AS first_bloods,
                AVG(mp.acs)                                      AS avg_acs,
                CASE WHEN SUM(m.team1_score + m.team2_score) > 0
                     THEN SUM(mp.kills) * 1.0 / SUM(m.team1_score + m.team2_score)
                     ELSE NULL END                                AS kpr,
                CASE WHEN SUM(mp.deaths) > 0
                     THEN SUM(mp.kills) * 1.0 / SUM(mp.deaths)
                     ELSE SUM(mp.kills) * 1.0 END                 AS kd,
                CASE WHEN p.games_played > 0
                     THEN p.wins * 1.0 / p.games_played
                     ELSE 0 END                                   AS win_rate
            FROM players p
            JOIN match_players mp ON mp.discord_id = p.discord_id
            JOIN matches m ON m.id = mp.match_id
            WHERE p.games_played > 0
            GROUP BY p.discord_id
            ORDER BY p.elo DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def record_match(
    winner: str,
    reported_by: str,
    team1: list[dict],
    team2: list[dict],
    elo_updates: dict[str, tuple[float, float]],
    map_name: str | None = None,
    team1_score: int | None = None,
    team2_score: int | None = None,
    screenshot_path: str | None = None,
) -> int:
    """
    team1 / team2: list of dicts with keys discord_id, agent, kills, deaths,
    assists, and optionally acs, first_bloods, plants, defuses, econ_rating.
    elo_updates: {discord_id: (elo_before, elo_after)}
    """
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO matches
                (played_at, reported_by, winner, map_name, team1_score,
                 team2_score, screenshot_path, confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (time.time(), reported_by, winner, map_name, team1_score, team2_score, screenshot_path),
        )
        match_id = cur.lastrowid

        for team_name, roster in (("team1", team1), ("team2", team2)):
            for p in roster:
                before, after = elo_updates[p["discord_id"]]
                conn.execute(
                    """
                    INSERT INTO match_players
                        (match_id, discord_id, team, agent, kills, deaths, assists,
                         acs, first_bloods, plants, defuses, econ_rating,
                         elo_before, elo_after)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        p["discord_id"],
                        team_name,
                        p.get("agent"),
                        p.get("kills", 0),
                        p.get("deaths", 0),
                        p.get("assists", 0),
                        p.get("acs"),
                        p.get("first_bloods", 0) or 0,
                        p.get("plants", 0) or 0,
                        p.get("defuses", 0) or 0,
                        p.get("econ_rating"),
                        before,
                        after,
                    ),
                )
                won = (team_name == winner)
                conn.execute(
                    """
                    UPDATE players
                    SET elo = ?,
                        wins = wins + ?,
                        losses = losses + ?,
                        kills = kills + ?,
                        deaths = deaths + ?,
                        assists = assists + ?,
                        games_played = games_played + 1
                    WHERE discord_id = ?
                    """,
                    (
                        after,
                        1 if won and winner != "draw" else 0,
                        1 if (not won) and winner != "draw" else 0,
                        p.get("kills", 0),
                        p.get("deaths", 0),
                        p.get("assists", 0),
                        p["discord_id"],
                    ),
                )
        return match_id


def get_recent_matches(limit: int = 10):
    with get_conn() as conn:
        matches = conn.execute(
            "SELECT * FROM matches ORDER BY played_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for m in matches:
            players = conn.execute(
                """
                SELECT mp.*, p.display_name
                FROM match_players mp
                JOIN players p ON p.discord_id = mp.discord_id
                WHERE mp.match_id = ?
                """,
                (m["id"],),
            ).fetchall()
            result.append({"match": m, "players": players})
        return result

"""
SQLite data layer for the Valorant Weeklies bot.

Everything (the Discord bot and the companion leaderboard web page) reads
and writes this same file, so no separate database server is needed.
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).parent / "weeklies.db"))

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
    elo_before      REAL,
    elo_after       REAL,
    PRIMARY KEY (match_id, discord_id)
);
"""


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
    with get_conn() as conn:
        conn.executescript(SCHEMA)


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


def find_player_by_riot_name(riot_name: str) -> sqlite3.Row | None:
    """Best-effort fuzzy match: exact match first, then case-insensitive
    match on the name portion before '#'."""
    with get_conn() as conn:
        exact = conn.execute(
            "SELECT * FROM players WHERE riot_name = ? COLLATE NOCASE", (riot_name,)
        ).fetchone()
        if exact:
            return exact
        name_part = riot_name.split("#")[0]
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


def record_match(
    winner: str,
    reported_by: str,
    team1: list[dict],
    team2: list[dict],
    elo_updates: dict[str, tuple[float, float]],
    map_name: str | None = None,
) -> int:
    """
    team1 / team2: list of dicts with keys discord_id, agent, kills, deaths, assists
    elo_updates: {discord_id: (elo_before, elo_after)}
    """
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO matches (played_at, reported_by, winner, map_name, confirmed) "
            "VALUES (?, ?, ?, ?, 1)",
            (time.time(), reported_by, winner, map_name),
        )
        match_id = cur.lastrowid

        for team_name, roster in (("team1", team1), ("team2", team2)):
            for p in roster:
                before, after = elo_updates[p["discord_id"]]
                conn.execute(
                    """
                    INSERT INTO match_players
                        (match_id, discord_id, team, agent, kills, deaths, assists,
                         elo_before, elo_after)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        p["discord_id"],
                        team_name,
                        p.get("agent"),
                        p.get("kills", 0),
                        p.get("deaths", 0),
                        p.get("assists", 0),
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

"""
db.py
Data-access layer for the GMI Trade Memo app, supporting two backends:

- Postgres (e.g. a free Supabase project) -- used whenever a DATABASE_URL
  is configured. This is durable: data survives app redeploys, sleep/wake
  cycles, and container restarts. Use this for the real deployment.
- Local SQLite file -- automatic fallback when no DATABASE_URL is set.
  Convenient for quick local testing on a laptop, but NOT durable on
  Streamlit Community Cloud (its filesystem is ephemeral), so this should
  not be relied on for a real semester's data.

Every other module in this app (app.py, export_blotter.py, team_codes.py)
talks to the functions below and never touches SQL directly, so which
backend is active is invisible to the rest of the codebase.

Row access: both backends return dict-like rows (sqlite3.Row on SQLite,
psycopg2 RealDictCursor rows on Postgres), so `row["column_name"]` works
identically either way.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "trade_memos.db"           # SQLite fallback only
SCHEMA_SQLITE_PATH = BASE_DIR / "schema_sqlite.sql"
SCHEMA_POSTGRES_PATH = BASE_DIR / "schema_postgres.sql"

MAX_TRADES_PER_TEAM = 3


def _database_url() -> str | None:
    """Looks for DATABASE_URL as an environment variable (handy for local
    CLI scripts) or a Streamlit secret (how the deployed app gets it).
    Returns None if neither is set, which selects the SQLite fallback."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("DATABASE_URL")
    except Exception:
        return None


BACKEND = "postgres" if _database_url() else "sqlite"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn():
    if BACKEND == "postgres":
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(_database_url(), cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _run(conn, sql: str, params: tuple = ()):
    """Executes one statement and returns a cursor, on either backend.

    Every query in this file is written with '?' placeholders (SQLite
    style); for Postgres they're translated to '%s' here so the rest of
    the file doesn't need two copies of every query. Both SQLite (3.35+)
    and Postgres support a RETURNING clause, which this file relies on to
    fetch a newly-inserted row's id without backend-specific code.
    """
    if BACKEND == "postgres":
        cur = conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur
    else:
        return conn.execute(sql, params)


def init_db() -> None:
    """Create tables if they do not already exist."""
    schema_path = SCHEMA_POSTGRES_PATH if BACKEND == "postgres" else SCHEMA_SQLITE_PATH
    script = schema_path.read_text()
    with get_conn() as conn:
        if BACKEND == "postgres":
            conn.cursor().execute(script)
        else:
            conn.executescript(script)


# --------------------------------------------------------------------------
# Teams / auth
# --------------------------------------------------------------------------

def upsert_team(section: str, team: str, access_code: str) -> None:
    with get_conn() as conn:
        _run(
            conn,
            """
            INSERT INTO teams (section, team, access_code)
            VALUES (?, ?, ?)
            ON CONFLICT(section, team) DO UPDATE SET access_code = excluded.access_code
            """,
            (section, team, access_code),
        )


def list_teams() -> list:
    with get_conn() as conn:
        return _run(conn, "SELECT * FROM teams ORDER BY section, team").fetchall()


def check_team_login(section: str, team: str, access_code: str) -> bool:
    with get_conn() as conn:
        row = _run(
            conn,
            "SELECT 1 FROM teams WHERE section = ? AND team = ? AND access_code = ?",
            (section, team, access_code.strip()),
        ).fetchone()
        return row is not None


# --------------------------------------------------------------------------
# Trades
# --------------------------------------------------------------------------

def get_team_trades(section: str, team: str) -> list:
    with get_conn() as conn:
        return _run(
            conn,
            "SELECT * FROM trades WHERE section = ? AND team = ? ORDER BY trade_no",
            (section, team),
        ).fetchall()


def get_trade(trade_id: int):
    with get_conn() as conn:
        return _run(conn, "SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()


def next_trade_no(section: str, team: str) -> int | None:
    """Returns the next available trade_no (1..MAX_TRADES_PER_TEAM), or None if full."""
    existing = {r["trade_no"] for r in get_team_trades(section, team)}
    for n in range(1, MAX_TRADES_PER_TEAM + 1):
        if n not in existing:
            return n
    return None


def create_draft(section: str, team: str, trade_no: int) -> int:
    now = _now()
    with get_conn() as conn:
        cur = _run(
            conn,
            """
            INSERT INTO trades (section, team, trade_no, status, created_at, updated_at)
            VALUES (?, ?, ?, 'draft', ?, ?)
            RETURNING id
            """,
            (section, team, trade_no, now, now),
        )
        return cur.fetchone()["id"]


def save_draft(trade_id: int, fields: dict[str, Any]) -> None:
    """Update any subset of editable fields on a draft trade."""
    fields = dict(fields)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [trade_id]
    with get_conn() as conn:
        _run(conn, f"UPDATE trades SET {set_clause} WHERE id = ?", values)


def submit_trade(trade_id: int) -> None:
    now = _now()
    with get_conn() as conn:
        _run(
            conn,
            """
            UPDATE trades
            SET status = 'submitted', submitted_at = ?, start_date = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, now, trade_id),
        )


def set_end_date(trade_id: int, end_date: str) -> None:
    """The ONLY field a submitted trade may still have changed."""
    with get_conn() as conn:
        _run(
            conn,
            "UPDATE trades SET end_date = ?, updated_at = ? WHERE id = ? AND status = 'submitted'",
            (end_date, _now(), trade_id),
        )


def all_trades() -> list:
    with get_conn() as conn:
        return _run(conn, "SELECT * FROM trades ORDER BY section, team, trade_no").fetchall()


# --------------------------------------------------------------------------
# Reset / cleanup (used by the Instructor view's "danger zone")
# --------------------------------------------------------------------------

def delete_trades_for_teams(pairs: list[tuple[str, str]]) -> int:
    """Delete every trade belonging to any of the given (section, team)
    pairs. Returns the number of trade rows deleted."""
    if not pairs:
        return 0
    deleted = 0
    with get_conn() as conn:
        for section, team in pairs:
            cur = _run(conn, "DELETE FROM trades WHERE section = ? AND team = ?", (section, team))
            deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return deleted


def delete_teams(pairs: list[tuple[str, str]]) -> int:
    """Delete the given (section, team) rows from the teams table. Does NOT
    touch trades -- call delete_trades_for_teams first if that's wanted too.
    Returns the number of team rows deleted."""
    if not pairs:
        return 0
    deleted = 0
    with get_conn() as conn:
        for section, team in pairs:
            cur = _run(conn, "DELETE FROM teams WHERE section = ? AND team = ?", (section, team))
            deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return deleted


def delete_all_trades() -> None:
    with get_conn() as conn:
        _run(conn, "DELETE FROM trades")


def delete_all_teams() -> None:
    with get_conn() as conn:
        _run(conn, "DELETE FROM teams")

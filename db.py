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

import json
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
    pairs, and any correction history for those trades. Returns the
    number of trade rows deleted."""
    if not pairs:
        return 0
    deleted = 0
    with get_conn() as conn:
        for section, team in pairs:
            _run(
                conn,
                "DELETE FROM trade_corrections WHERE trade_id IN "
                "(SELECT id FROM trades WHERE section = ? AND team = ?)",
                (section, team),
            )
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
        _run(conn, "DELETE FROM trade_corrections")
        _run(conn, "DELETE FROM trades")


def delete_all_teams() -> None:
    with get_conn() as conn:
        _run(conn, "DELETE FROM teams")


# --------------------------------------------------------------------------
# Instructor corrections to an already-submitted trade
# --------------------------------------------------------------------------
# Deliberately separate from save_draft/submit_trade: this is the ONLY
# sanctioned way to change a locked trade's fields (other than end_date,
# which students themselves can still set). It is never exposed to
# students -- app.py only calls this from the Instructor view, gated by
# INSTRUCTOR_CODE -- and every call is logged with a mandatory reason and
# a before/after diff, so there's a permanent record of what changed and
# why, visible to both the instructor and that trade's own team.

# Fields eligible for instructor correction. Deliberately excludes
# identity/audit fields (id, section, team, trade_no, status, timestamps)
# -- those aren't meant to be hand-edited even by an instructor; if a
# trade is fundamentally in the wrong place, that's a job for the Reset
# tools, not a "correction".
CORRECTABLE_FIELDS = {
    "submitter_last_name", "submitter_first_name", "submitter_email", "submitter_uni",
    "trade_title", "total_legs",
    "leg1_ticker", "leg1_direction", "leg1_exposure_pct",
    "leg2_ticker", "leg2_direction",
    "single_leg_gain", "single_leg_loss",
    "joint_limit_flag", "joint_gain", "joint_loss",
    "leg1_gain", "leg1_loss", "leg2_gain", "leg2_loss",
}


def correct_trade(trade_id: int, field_updates: dict[str, Any], reason: str) -> dict:
    """Applies a correction to an already-submitted (or draft) trade's
    fields, logging a before/after diff and the stated reason to
    trade_corrections. Only keys in CORRECTABLE_FIELDS are considered;
    anything else in field_updates is ignored. Only fields whose value
    actually changes are written and logged -- passing back the same
    value a field already has is a no-op for that field. Raises ValueError
    if the trade doesn't exist, no fields actually changed, or reason is
    blank. Returns the diff that was recorded, as {field: {"old","new"}}.
    """
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reason is required for every correction.")

    current = get_trade(trade_id)
    if current is None:
        raise ValueError(f"No trade with id {trade_id}.")

    diff = {}
    to_write = {}
    for field, new_value in field_updates.items():
        if field not in CORRECTABLE_FIELDS:
            continue
        old_value = current[field]
        # Compare as strings to avoid false positives from int/float/None
        # type differences between what a form submits and what's stored.
        if str(old_value) == str(new_value):
            continue
        diff[field] = {"old": old_value, "new": new_value}
        to_write[field] = new_value

    if not diff:
        raise ValueError("Nothing to change -- every value matches what's already stored.")

    now = _now()
    to_write["updated_at"] = now
    with get_conn() as conn:
        set_clause = ", ".join(f"{k} = ?" for k in to_write)
        values = list(to_write.values()) + [trade_id]
        _run(conn, f"UPDATE trades SET {set_clause} WHERE id = ?", values)
        _run(
            conn,
            "INSERT INTO trade_corrections (trade_id, corrected_at, reason, changes) VALUES (?, ?, ?, ?)",
            (trade_id, now, reason, json.dumps(diff)),
        )
    return diff


def get_corrections(trade_id: int) -> list:
    """Correction history for one trade, newest first."""
    with get_conn() as conn:
        return _run(
            conn,
            "SELECT * FROM trade_corrections WHERE trade_id = ? ORDER BY corrected_at DESC",
            (trade_id,),
        ).fetchall()

"""
db.py
Thin SQLite data-access layer for the GMI Trade Memo app.
No ORM on purpose -- this keeps the whole persistence layer in one
readable file and avoids an extra dependency for a single-file DB.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "trade_memos.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

MAX_TRADES_PER_TEAM = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they do not already exist."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_PATH.read_text())


# --------------------------------------------------------------------------
# Teams / auth
# --------------------------------------------------------------------------

def upsert_team(section: str, team: str, access_code: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO teams (section, team, access_code)
            VALUES (?, ?, ?)
            ON CONFLICT(section, team) DO UPDATE SET access_code = excluded.access_code
            """,
            (section, team, access_code),
        )


def list_teams() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM teams ORDER BY section, team").fetchall()


def check_team_login(section: str, team: str, access_code: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM teams WHERE section = ? AND team = ? AND access_code = ?",
            (section, team, access_code.strip()),
        ).fetchone()
        return row is not None


# --------------------------------------------------------------------------
# Trades
# --------------------------------------------------------------------------

def get_team_trades(section: str, team: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM trades WHERE section = ? AND team = ? ORDER BY trade_no",
            (section, team),
        ).fetchall()


def get_trade(trade_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()


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
        cur = conn.execute(
            """
            INSERT INTO trades (section, team, trade_no, status, created_at, updated_at)
            VALUES (?, ?, ?, 'draft', ?, ?)
            """,
            (section, team, trade_no, now, now),
        )
        return cur.lastrowid


def save_draft(trade_id: int, fields: dict[str, Any]) -> None:
    """Update any subset of editable fields on a draft trade."""
    fields = dict(fields)
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [trade_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE trades SET {set_clause} WHERE id = ?", values)


def submit_trade(trade_id: int) -> None:
    now = _now()
    with get_conn() as conn:
        conn.execute(
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
        conn.execute(
            "UPDATE trades SET end_date = ?, updated_at = ? WHERE id = ? AND status = 'submitted'",
            (end_date, _now(), trade_id),
        )


def all_trades() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM trades ORDER BY section, team, trade_no").fetchall()

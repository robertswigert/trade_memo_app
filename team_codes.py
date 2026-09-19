"""
team_codes.py
Shared logic for generating team access codes, used by both:
  - seed_teams.py (command-line, for local/manual use)
  - the "Generate / regenerate team codes" button in the Instructor view
    of app.py (so this can be done entirely by clicking, once deployed,
    with no terminal access to the server needed)
"""
from __future__ import annotations

import csv
import secrets
import string
from pathlib import Path

import db

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ROSTER = BASE_DIR / "data" / "team_roster.csv"


def gen_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    # avoid visually ambiguous characters (0/O, 1/I/L)
    alphabet = alphabet.translate({ord(c): None for c in "0O1IL"})
    return "".join(secrets.choice(alphabet) for _ in range(length))


def read_roster(roster_path: Path = DEFAULT_ROSTER) -> list[tuple[str, str]]:
    """Reads (section, team) pairs from a roster CSV."""
    pairs = []
    with open(roster_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pairs.append((row["section"].strip(), row["team"].strip()))
    return pairs


def seed_from_roster(roster_path: Path = DEFAULT_ROSTER) -> list[dict]:
    """Reads section/team pairs from roster_path, generates a fresh random
    code for each, writes them to the teams table, and returns the list of
    {section, team, access_code} dicts so the caller can display/download
    them. Re-running this OVERWRITES every existing code for teams still in
    the roster, and ADDS any new ones -- it does NOT remove teams that used
    to be in an older roster but aren't anymore; see db.delete_teams /
    db.delete_all_teams for that."""
    db.init_db()
    rows_out = []
    for section, team in read_roster(roster_path):
        code = gen_code()
        db.upsert_team(section, team, code)
        rows_out.append({"section": section, "team": team, "access_code": code})
    return rows_out


def codes_to_csv_bytes(rows: list[dict]) -> bytes:
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["section", "team", "access_code"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")

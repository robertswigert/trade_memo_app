"""
seed_teams.py
Command-line convenience wrapper for LOCAL use (e.g. testing on your own
laptop before deploying). Once the app is deployed, use the "Generate /
regenerate team codes" button in the Instructor view instead -- that runs
the same logic (see team_codes.py) without needing terminal access to
wherever the app is hosted.

Usage:
    python seed_teams.py
    python seed_teams.py --roster path/to/other_roster.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

from team_codes import DEFAULT_ROSTER, seed_from_roster, codes_to_csv_bytes

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_CODES = BASE_DIR / "data" / "team_access_codes.csv"


def main(roster_path: Path) -> None:
    rows_out = seed_from_roster(roster_path)
    OUTPUT_CODES.write_bytes(codes_to_csv_bytes(rows_out))
    print(f"Seeded {len(rows_out)} teams. Codes written to {OUTPUT_CODES}")
    print("Distribute each row's access_code ONLY to that team's designated submitter.")
    print("Re-running this script regenerates and overwrites all codes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    args = parser.parse_args()
    main(args.roster)

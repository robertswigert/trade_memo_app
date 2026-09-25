"""
validation.py
Validates Bloomberg-style tickers against an instructor-maintained
permitted-instrument list.

Design note
-----------
A whole-string exact-match whitelist doesn't work well for this class:
futures roots roll every semester (GCM6 -> GCZ6 -> GCH7 ...), options carry
strike/expiry in the ticker, and corporate/government bonds are identified
by one-off CUSIP/ISIN-style strings that can't be enumerated in advance.

So permitted_tickers.csv holds *patterns*, not just literal tickers, e.g.:

    SPY US Equity
    GC* Comdty
    * Curncy
    * Index

`*` is a wildcard (fnmatch semantics). A ticker is APPROVED if it matches
any pattern. Bond/CDS-style instruments (yellow key Corp/Govt/Muni) can
never be fully whitelisted in advance, so instead of hard-blocking them the
validator returns a "needs_review" status the instructor can approve
manually, rather than silently accepting or unfairly rejecting them.
"""
from __future__ import annotations

import csv
import fnmatch
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PERMITTED_TICKERS_PATH = BASE_DIR / "data" / "permitted_tickers.csv"

# Bloomberg "yellow key" security-type suffixes we recognize at all.
KNOWN_YELLOW_KEYS = {
    "EQUITY", "INDEX", "CURNCY", "COMDTY", "CORP", "GOVT", "MUNI",
    "PFD", "LOAN", "MTGE", "M-MKT",
}

# Yellow keys that identify one-off fixed income / credit instruments which
# cannot be enumerated in a static whitelist -> flagged for manual review
# instead of hard-rejected.
REVIEW_REQUIRED_KEYS = {"CORP", "GOVT", "MUNI", "PFD", "LOAN", "MTGE", "M-MKT"}


@dataclass
class TickerCheck:
    ticker: str
    status: str          # 'approved' | 'needs_review' | 'invalid_format' | 'rejected'
    message: str

    @property
    def blocks_submission(self) -> bool:
        # Only outright bad formatting or a non-whitelisted, non-bond ticker
        # blocks final submission. 'needs_review' is allowed through so a
        # legitimate one-off bond trade isn't stuck -- the instructor flags
        # it for a manual look in the review queue instead.
        return self.status in ("invalid_format", "rejected")


def _load_patterns() -> list[str]:
    if not PERMITTED_TICKERS_PATH.exists():
        return []
    patterns = []
    with open(PERMITTED_TICKERS_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            val = row[0].strip()
            if not val or val.startswith("#"):
                continue
            patterns.append(val.upper())
    return patterns


def _yellow_key(ticker: str) -> str | None:
    parts = ticker.strip().split()
    if len(parts) < 2:
        return None
    # yellow key is always the last token, except "M-MKT" style two-word keys
    return parts[-1].upper()


def check_ticker(raw_ticker: str) -> TickerCheck:
    ticker = (raw_ticker or "").strip()
    if not ticker or ticker.upper() in {"NA", "N/A"}:
        return TickerCheck(ticker, "rejected", "Ticker is required.")

    yk = _yellow_key(ticker)
    if yk is None or yk not in KNOWN_YELLOW_KEYS:
        return TickerCheck(
            ticker,
            "invalid_format",
            f"'{ticker}' doesn't look like a Bloomberg ticker "
            f"(expected a security-type suffix like Equity, Index, Curncy, "
            f"Comdty, Corp, or Govt).",
        )

    patterns = _load_patterns()
    ticker_u = ticker.upper()
    if any(fnmatch.fnmatch(ticker_u, pat) for pat in patterns):
        return TickerCheck(ticker, "approved", "On the permitted instrument list.")

    if yk in REVIEW_REQUIRED_KEYS:
        return TickerCheck(
            ticker,
            "needs_review",
            f"'{ticker}' is a {yk.title()} instrument not on the standing "
            f"whitelist (bonds/CDS are identified case by case). Allowed "
            f"through, flagged for instructor review.",
        )

    return TickerCheck(
        ticker,
        "rejected",
        f"'{ticker}' is not on the permitted instrument list. "
        f"Ask the instructor to add it to data/permitted_tickers.csv "
        f"if it should be allowed.",
    )


def check_trade_tickers(leg1_ticker: str, total_legs: int, leg2_ticker: str | None) -> list[TickerCheck]:
    checks = [check_ticker(leg1_ticker)]
    if total_legs == 2:
        checks.append(check_ticker(leg2_ticker))
    return checks

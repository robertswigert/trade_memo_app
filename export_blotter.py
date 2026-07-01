"""
export_blotter.py
Exports all trades (or one section) to an .xlsx file whose column layout
matches the instructor's existing master "Blotter" tab, so it drops
straight into the existing semester-tracking workflow.
"""
from __future__ import annotations

import io
from datetime import datetime

import openpyxl

import db

BLOTTER_COLUMNS = [
    "section", "team", "start_date", "end_date", "trade_no", "trade_name",
    "total_legs", "leg_1_direction", "leg_1_ticker", "leg_1_exp",
    "leg_2_direction", "leg_2_ticker",
    "sing_leg_take_prof", "sing_leg_stop_loss",
    "symmetric_lmt", "sym_lmt_take_prof", "sym_lmt_stop_loss",
    "leg_1_take_prof", "let_1_stop_loss", "leg_2_take_prof", "let_2_stop_loss",
]


def _row_for(trade: "db.sqlite3.Row") -> list:
    return [
        trade["section"],
        trade["team"],
        trade["start_date"],
        trade["end_date"],
        trade["trade_no"],
        trade["trade_title"],
        trade["total_legs"],
        trade["leg1_direction"],
        trade["leg1_ticker"],
        trade["leg1_exposure_pct"],
        trade["leg2_direction"],
        trade["leg2_ticker"],
        trade["single_leg_gain"],
        trade["single_leg_loss"],
        trade["joint_limit_flag"],
        trade["joint_gain"],
        trade["joint_loss"],
        trade["leg1_gain"],
        trade["leg1_loss"],
        trade["leg2_gain"],
        trade["leg2_loss"],
    ]


def build_blotter_workbook(submitted_only: bool = True) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Blotter"
    ws.append(BLOTTER_COLUMNS)

    for trade in db.all_trades():
        if submitted_only and trade["status"] != "submitted":
            continue
        ws.append(_row_for(trade))

    for col_cells in ws.columns:
        length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 40)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_confirmation_text(trade: "db.sqlite3.Row") -> str:
    """A downloadable confirmation the submitter can save/print for their
    records (replaces the old 'email confirmation -> PDF -> Canvas' step)."""
    lines = [
        "GMI Trade Memo -- Submission Confirmation",
        "=" * 45,
        f"Submitted at (UTC): {trade['submitted_at']}",
        f"Section: {trade['section']}    Team: {trade['team']}    Trade #: {trade['trade_no']}",
        f"Submitter: {trade['submitter_first_name']} {trade['submitter_last_name']} "
        f"({trade['submitter_uni']}, {trade['submitter_email']})",
        "",
        f"Trade Title: {trade['trade_title']}",
        f"Legs: {trade['total_legs']}",
        f"  Leg 1: {trade['leg1_direction']} {trade['leg1_ticker']}"
        + (f"  ({trade['leg1_exposure_pct']}% of exposure)" if trade["leg1_exposure_pct"] is not None else ""),
    ]
    if trade["total_legs"] == 2:
        lines.append(f"  Leg 2: {trade['leg2_direction']} {trade['leg2_ticker']}")
    lines += [
        "",
        f"Single-leg limits -- Gain: {trade['single_leg_gain']}  Loss: {trade['single_leg_loss']}",
        f"Joint trade limit set: {trade['joint_limit_flag']}  "
        f"Gain: {trade['joint_gain']}  Loss: {trade['joint_loss']}",
        f"Leg 1 limits -- Gain: {trade['leg1_gain']}  Loss: {trade['leg1_loss']}",
        f"Leg 2 limits -- Gain: {trade['leg2_gain']}  Loss: {trade['leg2_loss']}",
        "",
        "This trade is now locked. Only an end date may be added after submission.",
        f"Generated: {datetime.utcnow().isoformat(timespec='seconds')} UTC",
    ]
    return "\n".join(lines)

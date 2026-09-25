"""
app.py
Streamlit front end for the GMI Trade Memo submission tool.

Run locally:
    streamlit run app.py

Deploy: push this repo to GitHub and point Streamlit Community Cloud
(share.streamlit.io) at app.py. See README.md for full instructions.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import streamlit as st

import db
import export_blotter
import team_codes
from validation import check_trade_tickers

BASE_DIR = Path(__file__).resolve().parent
CBS_LOGO_PATH = BASE_DIR / "assets" / "cbs_hermes_icon.png"

st.set_page_config(
    page_title="GMI Trade Memo",
    page_icon=str(CBS_LOGO_PATH) if CBS_LOGO_PATH.exists() else "\U0001F4C8",
    layout="centered",
)
if CBS_LOGO_PATH.exists():
    # Places the CBS icon at the top of the sidebar (Streamlit's standard
    # spot for an app logo); falls back silently if the asset is missing
    # so a fresh checkout without the logo file still runs fine.
    st.logo(str(CBS_LOGO_PATH))

db.init_db()

INSTRUCTOR_CODE = os.environ.get("GMI_INSTRUCTOR_CODE", st.secrets.get("INSTRUCTOR_CODE", "changeme"))


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def page_header(title: str) -> None:
    """Page title with the CBS Hermes icon right-aligned beside it -- per
    CBS's own brand guidelines for standalone use of the icon (right-aligned
    along the top, never centered horizontally). Falls back to a plain
    title if the logo asset isn't present."""
    if CBS_LOGO_PATH.exists():
        col_title, col_logo = st.columns([5, 1])
        with col_title:
            st.title(title)
        with col_logo:
            st.image(str(CBS_LOGO_PATH), width=64)
    else:
        st.title(title)


def status_badge(status: str) -> str:
    return "\U0001F7E2 Submitted" if status == "submitted" else "\U0001F7E1 Draft"


def none_if_blank(v: str | None):
    v = (v or "").strip()
    return v if v else None


def render_ticker_feedback(checks) -> bool:
    """Shows validation results; returns True if OK to submit (final)."""
    ok_to_submit = True
    for c in checks:
        if c.status == "approved":
            st.success(f"{c.ticker}: {c.message}")
        elif c.status == "needs_review":
            st.warning(f"{c.ticker}: {c.message}")
        else:
            st.error(f"{c.ticker}: {c.message}")
        if c.blocks_submission:
            ok_to_submit = False
    return ok_to_submit


# --------------------------------------------------------------------------
# Trade edit form (used for new drafts and re-editing existing drafts)
# --------------------------------------------------------------------------

def trade_form(trade, section: str, team: str):
    t = dict(trade) if trade is not None else {}
    key_suffix = f"{t.get('id', 'new')}_{t.get('trade_no')}"

    st.subheader(f"Trade #{t.get('trade_no')}")

    # These two choices control which other fields appear below, so they
    # must live OUTSIDE st.form: widgets inside a form don't trigger a
    # rerun (and therefore don't update what's visible) until a submit
    # button is clicked. Putting them here makes the form reactive --
    # switching to "1 leg" immediately removes Leg 2 and the Joint option.
    total_legs = st.radio(
        "Trade legs", [1, 2], index=(t.get("total_legs") or 1) - 1, horizontal=True,
        key=f"legs_{key_suffix}",
    )

    if total_legs == 1:
        limit_mode = "Single leg"
        st.caption(
            "**Limit type: Single leg** -- the only option for a one-leg trade, since "
            "a joint/whole-trade limit would be identical to a single-leg limit here."
        )
    else:
        limit_mode = st.radio(
            "Limit type", ["Single leg", "Joint (whole trade)"],
            index=1 if t.get("joint_limit_flag") == "Yes" else 0, horizontal=True,
            key=f"limitmode_{key_suffix}",
            help="Single leg applies gain/loss % independently to each leg. "
                 "Joint applies gain/loss % to the combined position.",
        )

    with st.form(key=f"form_{key_suffix}"):
        col1, col2 = st.columns(2)
        with col1:
            last_name = st.text_input("Submitter last name", t.get("submitter_last_name") or "")
            email = st.text_input("Permanent CBS email", t.get("submitter_email") or "")
        with col2:
            first_name = st.text_input("Submitter first name", t.get("submitter_first_name") or "")
            uni = st.text_input("Columbia UNI", t.get("submitter_uni") or "")

        trade_title = st.text_input("Trade title", t.get("trade_title") or "")

        st.markdown("**Leg 1**")
        c1, c2, c3 = st.columns([2, 1, 1])
        leg1_ticker = c1.text_input("Leg 1 Bloomberg ticker", t.get("leg1_ticker") or "",
                                     placeholder="e.g. SPY US Equity")
        leg1_direction = c2.selectbox("Direction", ["Long", "Short"],
                                       index=0 if (t.get("leg1_direction") or "Long") == "Long" else 1,
                                       key=f"leg1dir_{key_suffix}")
        leg1_exposure = c3.number_input("Leg 1 exposure %", min_value=0.0, max_value=100.0,
                                         value=float(t.get("leg1_exposure_pct") or (100.0 if total_legs == 1 else 50.0)),
                                         step=1.0, disabled=(total_legs == 1), key=f"leg1exp_{key_suffix}")

        leg2_ticker, leg2_direction = None, None
        if total_legs == 2:
            st.markdown("**Leg 2**")
            c4, c5 = st.columns([2, 1])
            leg2_ticker = c4.text_input("Leg 2 Bloomberg ticker", t.get("leg2_ticker") or "",
                                         placeholder="e.g. FEZ US Equity", key=f"leg2tick_{key_suffix}")
            leg2_direction = c5.selectbox("Leg 2 direction", ["Long", "Short"],
                                           index=0 if (t.get("leg2_direction") or "Long") == "Long" else 1,
                                           key=f"leg2dir_{key_suffix}")
            st.caption(f"Leg 2 exposure will be recorded as {100 - leg1_exposure:.0f}% (the remainder).")

        st.markdown("**Risk management limits**")
        st.caption(
            f"Limit type: **{limit_mode}**. Enter each limit as a plain positive number "
            f"(e.g. 8 for an 8% move) -- take-profit is automatically recorded as a gain, "
            f"stop-loss is automatically recorded as a loss. Leave at 0 for no limit."
        )

        # Every field below is a MAGNITUDE (always >= 0 by construction, via
        # min_value=0.0). The correct sign is applied when building `fields`
        # further down -- this makes it structurally impossible to record a
        # take-profit as negative or a stop-loss as positive, regardless of
        # what a user types. Each also has an explicit, unique key: which of
        # these widgets even exist changes depending on total_legs/limit_mode,
        # so we don't want Streamlit guessing widget identity by position.
        single_leg_gain_mag = single_leg_loss_mag = 0.0
        leg1_gain_mag = leg1_loss_mag = leg2_gain_mag = leg2_loss_mag = 0.0
        joint_gain_mag = joint_loss_mag = 0.0

        if limit_mode == "Single leg":
            if total_legs == 1:
                c1, c2 = st.columns(2)
                single_leg_gain_mag = c1.number_input(
                    "Take-profit (gain) %", min_value=0.0, step=1.0,
                    value=abs(float(t.get("single_leg_gain") or 0.0)),
                    help="Positive number, e.g. 15 for a 15% take-profit. 0 = no limit.",
                    key=f"slgain_{key_suffix}")
                single_leg_loss_mag = c2.number_input(
                    "Stop-loss %", min_value=0.0, step=1.0,
                    value=abs(float(t.get("single_leg_loss") or 0.0)),
                    help="Positive number, e.g. 8 for an 8% stop-loss (recorded as -8%). 0 = no limit.",
                    key=f"slloss_{key_suffix}")
            else:
                st.caption("Independent gain/loss limit for each leg:")
                k1, k2, k3, k4 = st.columns(4)
                leg1_gain_mag = k1.number_input("Leg 1 take-profit %", min_value=0.0, step=1.0,
                                                 value=abs(float(t.get("leg1_gain") or 0.0)),
                                                 key=f"l1gain_{key_suffix}")
                leg1_loss_mag = k2.number_input("Leg 1 stop-loss %", min_value=0.0, step=1.0,
                                                 value=abs(float(t.get("leg1_loss") or 0.0)),
                                                 key=f"l1loss_{key_suffix}")
                leg2_gain_mag = k3.number_input("Leg 2 take-profit %", min_value=0.0, step=1.0,
                                                 value=abs(float(t.get("leg2_gain") or 0.0)),
                                                 key=f"l2gain_{key_suffix}")
                leg2_loss_mag = k4.number_input("Leg 2 stop-loss %", min_value=0.0, step=1.0,
                                                 value=abs(float(t.get("leg2_loss") or 0.0)),
                                                 key=f"l2loss_{key_suffix}")
        else:
            st.caption("Gain/loss limit for the combined trade (both legs exit together):")
            j1, j2 = st.columns(2)
            joint_gain_mag = j1.number_input(
                "Joint take-profit (gain) %", min_value=0.0, step=1.0,
                value=abs(float(t.get("joint_gain") or 0.0)),
                help="Positive number. 0 = no limit.", key=f"jgain_{key_suffix}")
            joint_loss_mag = j2.number_input(
                "Joint stop-loss %", min_value=0.0, step=1.0,
                value=abs(float(t.get("joint_loss") or 0.0)),
                help="Positive number, recorded as a negative loss. 0 = no limit.", key=f"jloss_{key_suffix}")

        save_col, submit_col = st.columns(2)
        save_clicked = save_col.form_submit_button("\U0001F4BE Save draft", width="stretch")
        submit_clicked = submit_col.form_submit_button("\u2705 Submit final (locks the trade)",
                                                         width="stretch", type="primary")

    joint_limit_flag = "Yes" if limit_mode == "Joint (whole trade)" else "No"

    fields = dict(
        submitter_last_name=none_if_blank(last_name),
        submitter_first_name=none_if_blank(first_name),
        submitter_email=none_if_blank(email),
        submitter_uni=none_if_blank(uni),
        trade_title=none_if_blank(trade_title),
        total_legs=total_legs,
        leg1_ticker=none_if_blank(leg1_ticker),
        leg1_direction=leg1_direction,
        leg1_exposure_pct=leg1_exposure,
        leg2_ticker=none_if_blank(leg2_ticker) if total_legs == 2 else None,
        leg2_direction=leg2_direction if total_legs == 2 else None,
        # Note: priced_assessment/thesis/implementation/objectives_scenarios
        # are intentionally not collected here anymore (narrative now lives
        # in a separate document the team submits) and are left out of this
        # dict entirely -- save_draft only updates the keys it's given, so
        # any old values already stored from before this change are left as-is.
        single_leg_gain=single_leg_gain_mag or None,
        single_leg_loss=-single_leg_loss_mag if single_leg_loss_mag else None,
        joint_limit_flag=joint_limit_flag,
        joint_gain=joint_gain_mag or None,
        joint_loss=-joint_loss_mag if joint_loss_mag else None,
        leg1_gain=leg1_gain_mag or None,
        leg1_loss=-leg1_loss_mag if leg1_loss_mag else None,
        leg2_gain=leg2_gain_mag or None,
        leg2_loss=-leg2_loss_mag if leg2_loss_mag else None,
    )

    if save_clicked:
        trade_id = t.get("id") or db.create_draft(section, team, t.get("trade_no"))
        db.save_draft(trade_id, fields)
        st.success("Draft saved. You can keep editing until you submit final.")
        st.rerun()

    if submit_clicked:
        checks = check_trade_tickers(leg1_ticker, total_legs, leg2_ticker)
        required_missing = [
            name for name, val in [
                ("submitter last name", last_name), ("submitter first name", first_name),
                ("email", email), ("UNI", uni), ("trade title", trade_title),
                ("leg 1 ticker", leg1_ticker),
            ] if not (val or "").strip()
        ]

        st.markdown("**Ticker validation**")
        tickers_ok = render_ticker_feedback(checks)

        if required_missing:
            st.error(f"Missing required field(s): {', '.join(required_missing)}. Save as a draft and finish these first.")
        elif not tickers_ok:
            st.error("Fix the ticker issue(s) above, then submit again. (You can still save as a draft.)")
        else:
            trade_id = t.get("id") or db.create_draft(section, team, t.get("trade_no"))
            db.save_draft(trade_id, fields)
            db.submit_trade(trade_id)
            st.success("Trade submitted and locked. Only an end date can be changed from here.")
            st.rerun()


def submitted_trade_view(trade):
    t = dict(trade)
    st.subheader(f"Trade #{t['trade_no']} \u2014 {t['trade_title']}  ({status_badge(t['status'])})")
    st.write(f"**Submitted:** {t['submitted_at']}  |  **Start date:** {t['start_date']}")
    leg_desc = f"{t['leg1_direction']} {t['leg1_ticker']}"
    if t["total_legs"] == 2:
        leg_desc += f"  /  {t['leg2_direction']} {t['leg2_ticker']}"
    st.write(f"**Legs:** {leg_desc}")

    if t["joint_limit_flag"] == "Yes":
        st.write(f"**Risk limits (joint, whole trade):** gain {t['joint_gain']}% / loss {t['joint_loss']}%")
    elif t["total_legs"] == 1:
        st.write(f"**Risk limits (single leg):** gain {t['single_leg_gain']}% / loss {t['single_leg_loss']}%")
    else:
        st.write(
            f"**Risk limits (per leg):** "
            f"Leg 1 gain {t['leg1_gain']}% / loss {t['leg1_loss']}%  |  "
            f"Leg 2 gain {t['leg2_gain']}% / loss {t['leg2_loss']}%"
        )

    # Narrative fields are no longer collected (the team's trade memo now
    # lives in a separate document) -- but if an older trade already has
    # this data stored from before that change, still show it rather than
    # silently hiding it.
    if any(t.get(k) for k in ("priced_assessment", "thesis", "implementation", "objectives_scenarios")):
        with st.expander("View saved trade memo narrative (legacy)"):
            if t.get("priced_assessment"):
                st.markdown(f"**1. Assess what is priced**\n\n{t['priced_assessment']}")
            if t.get("thesis"):
                st.markdown(f"**2. Thesis**\n\n{t['thesis']}")
            if t.get("implementation"):
                st.markdown(f"**3. Implementation**\n\n{t['implementation']}")
            if t.get("objectives_scenarios"):
                st.markdown(f"**4. Objectives / scenarios / limits**\n\n{t['objectives_scenarios']}")

    current_end = t.get("end_date")
    new_end = st.date_input(
        "End date (the only field you can still edit)",
        value=date.fromisoformat(current_end) if current_end else None,
    )
    if st.button("Save end date", key=f"end_{t['id']}"):
        db.set_end_date(t["id"], new_end.isoformat())
        st.success("End date saved.")
        st.rerun()

    st.download_button(
        "\U0001F4C4 Download submission confirmation",
        data=export_blotter.build_confirmation_text(db.get_trade(t["id"])),
        file_name=f"trade_memo_confirmation_{t['section']}_{t['team'].replace(' ', '_')}_{t['trade_no']}.txt",
        mime="text/plain",
        key=f"dl_{t['id']}",
    )


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def team_portal():
    page_header("\U0001F4C8 GMI Trade Memo Submission")
    st.caption("One designated submitter per team. Trades stay editable as drafts; "
               "once you hit Submit final the memo is locked (only the end date can change later).")

    teams = db.list_teams()
    if not teams:
        st.warning("No teams are set up yet. The instructor needs to run `python seed_teams.py` first.")
        return

    sections = sorted({row["section"] for row in teams})
    section = st.selectbox("Section", sections)
    team_names = sorted({row["team"] for row in teams if row["section"] == section})
    team = st.selectbox("Your team", team_names)
    code = st.text_input("Team access code", type="password")

    if not code:
        st.info("Enter your team's access code to view or submit trades.")
        return
    if not db.check_team_login(section, team, code):
        st.error("Incorrect access code for this team.")
        return

    st.success(f"Logged in as designated submitter for {team} ({section}).")

    trades = db.get_team_trades(section, team)
    for trade in trades:
        st.divider()
        if trade["status"] == "submitted":
            submitted_trade_view(trade)
        else:
            trade_form(trade, section, team)

    st.divider()
    existing_nos = {t["trade_no"] for t in trades}
    remaining = [n for n in range(1, db.MAX_TRADES_PER_TEAM + 1) if n not in existing_nos]
    if not remaining:
        st.info(f"Your team has already used all {db.MAX_TRADES_PER_TEAM} trade slots for the semester.")
    else:
        st.subheader("Start a new trade")
        if len(remaining) > 1:
            st.caption(
                "Trades don't need to be started in order -- pick whichever "
                "slot you're ready to work on. (A trade does NOT need to be "
                "submitted, or even saved as a draft, before you can start "
                "another one.)"
            )
            chosen = st.selectbox("Trade number", remaining, key="new_trade_no_select")
        else:
            chosen = remaining[0]
        trade_form({"trade_no": chosen}, section, team)


def instructor_portal():
    page_header("\U0001F393 Instructor View")
    code = st.text_input("Instructor access code", type="password")
    if code != INSTRUCTOR_CODE:
        if code:
            st.error("Incorrect instructor code.")
        return

    trades = db.all_trades()
    submitted = [t for t in trades if t["status"] == "submitted"]
    drafts = [t for t in trades if t["status"] == "draft"]
    st.write(f"**{len(submitted)} submitted** / {len(drafts)} in-progress drafts / {len(trades)} total")

    st.download_button(
        "\U0001F4E5 Download blotter (.xlsx, submitted trades only)",
        data=export_blotter.build_blotter_workbook(submitted_only=True),
        file_name="trade_blotter_export.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.download_button(
        "\U0001F4E5 Download blotter (.xlsx, including drafts)",
        data=export_blotter.build_blotter_workbook(submitted_only=False),
        file_name="trade_blotter_export_with_drafts.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.divider()
    st.subheader("All trades")
    for t in trades:
        st.write(
            f"{status_badge(t['status'])} \u2014 **{t['section']} / {t['team']}** "
            f"Trade #{t['trade_no']}: {t['trade_title'] or '(untitled)'}"
        )

    st.divider()
    st.subheader("Team access codes")

    # --- Add missing teams (safe, non-destructive): the action for the
    # common case of adding a couple of teams mid-semester. Existing teams
    # and their already-distributed codes are never touched.
    try:
        roster_pairs_for_add = set(team_codes.read_roster())
    except FileNotFoundError:
        roster_pairs_for_add = set()

    existing_pairs_for_add = {(r["section"], r["team"]) for r in db.list_teams()}
    missing_pairs = sorted(roster_pairs_for_add - existing_pairs_for_add)

    with st.expander(
        f"\u2795 Add teams from roster not yet in the database (safe)"
        + (f" -- {len(missing_pairs)} found" if missing_pairs else ""),
        expanded=bool(missing_pairs),
    ):
        if not missing_pairs:
            st.write("None found -- every team in `data/team_roster.csv` is already in the database.")
        else:
            st.write(f"{len(missing_pairs)} team(s) in your roster are not yet in the database:")
            st.dataframe(
                [{"section": s, "team": t} for s, t in missing_pairs],
                width="stretch", hide_index=True,
            )
            st.caption(
                "Adds these team(s) with a freshly generated access code each. "
                "Every team that already exists -- and its code -- is left "
                "completely untouched."
            )
            if st.button("Add missing team(s) with new access codes"):
                added = team_codes.add_missing_from_roster()
                st.success(f"Added {len(added)} team(s). See the current codes list below to get theirs.")
                st.rerun()

    # --- Regeneration (destructive) happens first, so if it runs this same
    # turn, the "current codes" view below already reflects the new codes.
    with st.expander("\u26a0\ufe0f Generate / regenerate ALL team access codes (danger zone)"):
        st.caption(
            "Reads section/team pairs from data/team_roster.csv, generates a "
            "**brand-new** random code for every team -- including ones "
            "already in the database -- and immediately **invalidates every "
            "existing code**. Only do this for a new semester or if a code "
            "leaked. To add a few new teams without disturbing everyone "
            "else's codes, use 'Add teams from roster' above instead."
        )
        if st.button("\U0001F510 Generate / regenerate all team access codes"):
            team_codes.seed_from_roster()
            st.success("Generated fresh codes for every team. See the current list below.")

    # --- Current codes (non-destructive): reads what's actually stored in
    # the database right now, so this works whether codes were generated
    # a minute ago or a month ago -- no need to regenerate just to see them.
    current_rows = [
        {"section": r["section"], "team": r["team"], "access_code": r["access_code"]}
        for r in db.list_teams()
    ]

    if not current_rows:
        st.info("No teams exist yet -- use 'Generate' above to create them.")
    else:
        show_codes = st.checkbox("Show current codes on screen", value=False)
        if show_codes:
            st.dataframe(current_rows, width="stretch", hide_index=True)
        st.download_button(
            "\U0001F4E5 Download current team access codes (.csv)",
            data=team_codes.codes_to_csv_bytes(current_rows),
            file_name="team_access_codes.csv",
            mime="text/csv",
        )
        st.caption(
            "This list is always the current, live codes -- safe to check back "
            "here any time. Contains every team's login code, so don't leave "
            "'Show current codes' on screen where others can see it, and "
            "distribute rows individually rather than posting the whole file."
        )

    st.divider()
    st.subheader("Reset teams / trades")
    st.caption(
        "Use this after updating data/team_roster.csv with real team names "
        "(e.g. replacing placeholder/test teams), or to start a new semester "
        "with a clean slate."
    )

    try:
        roster_pairs = set(team_codes.read_roster())
    except FileNotFoundError:
        roster_pairs = set()
        st.error("data/team_roster.csv not found -- can't compare against the roster.")

    db_team_pairs = {(r["section"], r["team"]) for r in db.list_teams()}
    stale_pairs = sorted(db_team_pairs - roster_pairs)

    with st.expander("\U0001F9F9 Remove stale teams (safe -- only removes teams NOT in the current roster)"):
        if not stale_pairs:
            st.write("None found -- every team in the database matches your current `data/team_roster.csv`.")
        else:
            st.write(f"{len(stale_pairs)} team(s) in the database are **not** in your current roster:")
            st.dataframe(
                [{"section": s, "team": t} for s, t in stale_pairs],
                width="stretch", hide_index=True,
            )
            st.caption(
                "This deletes these team(s) AND any trades already recorded "
                "under them (e.g. leftover test submissions). Teams that "
                "match your current roster are never touched by this."
            )
            confirm_stale = st.checkbox(
                "I understand this permanently deletes these teams and their trades.",
                key="confirm_remove_stale",
            )
            if st.button("Remove stale teams + their trades", disabled=not confirm_stale):
                trades_deleted = db.delete_trades_for_teams(stale_pairs)
                teams_deleted = db.delete_teams(stale_pairs)
                st.success(f"Removed {teams_deleted} stale team(s) and {trades_deleted} associated trade(s).")
                st.rerun()

    with st.expander("\U0001F4A3 Full reset -- wipe EVERYTHING and reseed from roster (nuclear)"):
        st.caption(
            "Deletes every team and every trade currently in the database "
            "(including any real, already-submitted trades -- not just "
            "stale/test ones), then recreates teams fresh from "
            "`data/team_roster.csv` with brand-new access codes. Use this "
            "only for a genuinely clean start, e.g. before a new semester."
        )
        confirm_text = st.text_input(
            "Type RESET (all caps) to confirm a full wipe", key="full_reset_confirm")
        if st.button("Full reset: wipe everything and reseed from roster",
                      disabled=(confirm_text.strip() != "RESET")):
            db.delete_all_trades()
            db.delete_all_teams()
            new_rows = team_codes.seed_from_roster()
            st.success(
                f"Wiped all data and reseeded {len(new_rows)} teams from the current roster. "
                f"Open 'Team access codes' above to view/download the new codes."
            )
            st.rerun()


# --------------------------------------------------------------------------

st.sidebar.title("GMI Trade Memo")
page = st.sidebar.radio("Go to", ["Team submission", "Instructor view"])
if page == "Team submission":
    team_portal()
else:
    instructor_portal()

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

import streamlit as st

import db
import export_blotter
import team_codes
from validation import check_trade_tickers

st.set_page_config(page_title="GMI Trade Memo", page_icon="\U0001F4C8", layout="centered")
db.init_db()

INSTRUCTOR_CODE = os.environ.get("GMI_INSTRUCTOR_CODE", st.secrets.get("INSTRUCTOR_CODE", "changeme"))


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

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

    st.subheader(f"Trade #{t.get('trade_no')}")

    with st.form(key=f"form_{t.get('id', 'new')}"):
        col1, col2 = st.columns(2)
        with col1:
            last_name = st.text_input("Submitter last name", t.get("submitter_last_name") or "")
            email = st.text_input("Permanent CBS email", t.get("submitter_email") or "")
        with col2:
            first_name = st.text_input("Submitter first name", t.get("submitter_first_name") or "")
            uni = st.text_input("Columbia UNI", t.get("submitter_uni") or "")

        trade_title = st.text_input("Trade title", t.get("trade_title") or "")
        total_legs = st.radio("Trade legs", [1, 2], index=(t.get("total_legs") or 1) - 1, horizontal=True)

        st.markdown("**Leg 1**")
        c1, c2, c3 = st.columns([2, 1, 1])
        leg1_ticker = c1.text_input("Leg 1 Bloomberg ticker", t.get("leg1_ticker") or "",
                                     placeholder="e.g. SPY US Equity")
        leg1_direction = c2.selectbox("Direction", ["Long", "Short"],
                                       index=0 if (t.get("leg1_direction") or "Long") == "Long" else 1)
        leg1_exposure = c3.number_input("Leg 1 exposure %", min_value=0.0, max_value=100.0,
                                         value=float(t.get("leg1_exposure_pct") or (100.0 if total_legs == 1 else 50.0)),
                                         step=1.0, disabled=(total_legs == 1))

        leg2_ticker, leg2_direction = None, None
        if total_legs == 2:
            st.markdown("**Leg 2**")
            c4, c5 = st.columns([2, 1])
            leg2_ticker = c4.text_input("Leg 2 Bloomberg ticker", t.get("leg2_ticker") or "",
                                         placeholder="e.g. FEZ US Equity")
            leg2_direction = c5.selectbox("Leg 2 direction", ["Long", "Short"],
                                           index=0 if (t.get("leg2_direction") or "Long") == "Long" else 1,
                                           key="leg2dir")
            st.caption(f"Leg 2 exposure will be recorded as {100 - leg1_exposure:.0f}% (the remainder).")

        st.markdown("**Trade memo narrative**")
        priced_assessment = st.text_area("1. Assess what is priced", t.get("priced_assessment") or "", height=100)
        thesis = st.text_area("2. State your thesis", t.get("thesis") or "", height=100)
        implementation = st.text_area("3. Explain trade implementation", t.get("implementation") or "", height=100)
        objectives_scenarios = st.text_area(
            "4. Set objectives, assess scenarios, set limits", t.get("objectives_scenarios") or "", height=120)

        st.markdown("**Limits**")
        l1, l2 = st.columns(2)
        single_leg_gain = l1.number_input("Single-leg gain limit %", value=float(t.get("single_leg_gain") or 0.0),
                                           step=1.0, help="Leave at 0 for no limit.")
        single_leg_loss = l2.number_input("Single-leg loss limit %", value=float(t.get("single_leg_loss") or 0.0),
                                           step=1.0, help="Leave at 0 for no limit.")

        joint_limit_flag = st.radio("Joint trade limit set?", ["No", "Yes"],
                                     index=1 if t.get("joint_limit_flag") == "Yes" else 0, horizontal=True)
        j1, j2 = st.columns(2)
        joint_gain = j1.number_input("Joint gain limit %", value=float(t.get("joint_gain") or 0.0), step=1.0,
                                      disabled=(joint_limit_flag == "No"))
        joint_loss = j2.number_input("Joint loss limit %", value=float(t.get("joint_loss") or 0.0), step=1.0,
                                      disabled=(joint_limit_flag == "No"))

        leg1_gain = leg1_loss = leg2_gain = leg2_loss = 0.0
        if total_legs == 2:
            st.caption("Optional: per-leg limits (in addition to, or instead of, the joint limit above)")
            k1, k2, k3, k4 = st.columns(4)
            leg1_gain = k1.number_input("Leg 1 gain %", value=float(t.get("leg1_gain") or 0.0), step=1.0)
            leg1_loss = k2.number_input("Leg 1 loss %", value=float(t.get("leg1_loss") or 0.0), step=1.0)
            leg2_gain = k3.number_input("Leg 2 gain %", value=float(t.get("leg2_gain") or 0.0), step=1.0)
            leg2_loss = k4.number_input("Leg 2 loss %", value=float(t.get("leg2_loss") or 0.0), step=1.0)

        save_col, submit_col = st.columns(2)
        save_clicked = save_col.form_submit_button("\U0001F4BE Save draft", use_container_width=True)
        submit_clicked = submit_col.form_submit_button("\u2705 Submit final (locks the trade)",
                                                         use_container_width=True, type="primary")

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
        priced_assessment=none_if_blank(priced_assessment),
        thesis=none_if_blank(thesis),
        implementation=none_if_blank(implementation),
        objectives_scenarios=none_if_blank(objectives_scenarios),
        single_leg_gain=single_leg_gain or None,
        single_leg_loss=single_leg_loss or None,
        joint_limit_flag=joint_limit_flag,
        joint_gain=joint_gain if joint_limit_flag == "Yes" else None,
        joint_loss=joint_loss if joint_limit_flag == "Yes" else None,
        leg1_gain=leg1_gain or None,
        leg1_loss=leg1_loss or None,
        leg2_gain=leg2_gain or None,
        leg2_loss=leg2_loss or None,
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
                ("thesis", thesis), ("implementation", implementation),
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

    with st.expander("View full trade memo"):
        st.markdown(f"**1. Assess what is priced**\n\n{t['priced_assessment']}")
        st.markdown(f"**2. Thesis**\n\n{t['thesis']}")
        st.markdown(f"**3. Implementation**\n\n{t['implementation']}")
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
    st.title("\U0001F4C8 GMI Trade Memo Submission")
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
    nxt = db.next_trade_no(section, team)
    if nxt is None:
        st.info(f"Your team has already used all {db.MAX_TRADES_PER_TEAM} trade slots for the semester.")
    else:
        st.subheader(f"Start Trade #{nxt}")
        trade_form({"trade_no": nxt}, section, team)


def instructor_portal():
    st.title("\U0001F393 Instructor View")
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
    st.caption(
        "Reads section/team pairs from data/team_roster.csv (edit that file in your "
        "GitHub repo to add/remove teams each semester), generates a fresh random "
        "code for every team, and lets you download the list to distribute privately "
        "to each team's designated submitter. **Regenerating invalidates all previous "
        "codes** -- useful if a code leaks, but don't click it mid-semester unless you "
        "mean to reset everyone."
    )
    if st.button("\U0001F510 Generate / regenerate all team access codes"):
        rows = team_codes.seed_from_roster()
        st.session_state["_new_codes"] = rows
        st.success(f"Generated codes for {len(rows)} teams.")

    if "_new_codes" in st.session_state:
        st.download_button(
            "\U0001F4E5 Download team access codes (.csv)",
            data=team_codes.codes_to_csv_bytes(st.session_state["_new_codes"]),
            file_name="team_access_codes.csv",
            mime="text/csv",
        )
        st.warning("This file contains every team's login code. Download it, then "
                   "distribute rows individually -- don't post the whole file "
                   "somewhere all students can see it.")

    st.subheader("Registered teams")
    st.dataframe(
        [{"section": r["section"], "team": r["team"]} for r in db.list_teams()],
        use_container_width=True,
    )


# --------------------------------------------------------------------------

st.sidebar.title("GMI Trade Memo")
page = st.sidebar.radio("Go to", ["Team submission", "Instructor view"])
if page == "Team submission":
    team_portal()
else:
    instructor_portal()

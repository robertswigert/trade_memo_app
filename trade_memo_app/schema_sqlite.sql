-- GMI Trade Memo database schema

CREATE TABLE IF NOT EXISTS teams (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section     TEXT NOT NULL,          -- e.g. 'B8213'
    team        TEXT NOT NULL,          -- e.g. 'MBA Juliett'
    access_code TEXT NOT NULL,          -- shared secret for the team's designated submitter
    UNIQUE(section, team)
);

CREATE TABLE IF NOT EXISTS trades (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    section                 TEXT NOT NULL,
    team                    TEXT NOT NULL,
    trade_no                INTEGER NOT NULL,           -- 1, 2, or 3 for the semester
    status                  TEXT NOT NULL DEFAULT 'draft',  -- 'draft' | 'submitted'

    submitter_last_name     TEXT,
    submitter_first_name    TEXT,
    submitter_email         TEXT,
    submitter_uni           TEXT,

    trade_title             TEXT,
    total_legs               INTEGER,             -- 1 or 2

    leg1_ticker             TEXT,
    leg1_direction          TEXT,                 -- 'Long' | 'Short'
    leg1_exposure_pct       REAL,

    leg2_ticker             TEXT,
    leg2_direction          TEXT,

    priced_assessment       TEXT,                 -- "Assess what is priced"
    thesis                  TEXT,                 -- "State your thesis"
    implementation          TEXT,                 -- "Explain trade implementation"
    objectives_scenarios    TEXT,                 -- "Set objectives, assess scenarios, set limits"

    single_leg_gain         REAL,
    single_leg_loss         REAL,

    joint_limit_flag        TEXT,                 -- 'Yes' | 'No'
    joint_gain              REAL,
    joint_loss              REAL,

    leg1_gain               REAL,
    leg1_loss                REAL,
    leg2_gain               REAL,
    leg2_loss                REAL,

    start_date               TEXT,                -- set automatically at final submission
    end_date                 TEXT,                -- only field editable after submission

    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL,
    submitted_at              TEXT,

    UNIQUE(section, team, trade_no)
);

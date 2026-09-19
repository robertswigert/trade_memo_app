-- GMI Trade Memo database schema (Postgres version)
-- Mirrors schema_sqlite.sql; kept as a separate file because primary-key
-- auto-increment syntax differs between SQLite and Postgres.

CREATE TABLE IF NOT EXISTS teams (
    id          SERIAL PRIMARY KEY,
    section     TEXT NOT NULL,
    team        TEXT NOT NULL,
    access_code TEXT NOT NULL,
    UNIQUE(section, team)
);

CREATE TABLE IF NOT EXISTS trades (
    id                      SERIAL PRIMARY KEY,
    section                 TEXT NOT NULL,
    team                    TEXT NOT NULL,
    trade_no                INTEGER NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'draft',

    submitter_last_name     TEXT,
    submitter_first_name    TEXT,
    submitter_email         TEXT,
    submitter_uni           TEXT,

    trade_title             TEXT,
    total_legs               INTEGER,

    leg1_ticker             TEXT,
    leg1_direction          TEXT,
    leg1_exposure_pct       REAL,

    leg2_ticker             TEXT,
    leg2_direction          TEXT,

    priced_assessment       TEXT,
    thesis                  TEXT,
    implementation          TEXT,
    objectives_scenarios    TEXT,

    single_leg_gain         REAL,
    single_leg_loss         REAL,

    joint_limit_flag        TEXT,
    joint_gain              REAL,
    joint_loss              REAL,

    leg1_gain               REAL,
    leg1_loss                REAL,
    leg2_gain               REAL,
    leg2_loss                REAL,

    start_date               TEXT,
    end_date                 TEXT,

    created_at                TEXT NOT NULL,
    updated_at                TEXT NOT NULL,
    submitted_at              TEXT,

    UNIQUE(section, team, trade_no)
);

"""The database schema. db.init() runs the steps that are new to the database."""

# Schema steps in order. Add steps only at the end, and only add things: the old version
# runs against the new schema while Render deploys. Never edit a deployed step.
MIGRATIONS = [
    # 1: the tables as they were when the app moved from SQLite to Postgres.
    """
CREATE TABLE visits (
  reference    TEXT PRIMARY KEY,
  token        TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  phone        TEXT NOT NULL,
  address      TEXT NOT NULL,
  reason       TEXT NOT NULL,
  visiting     TEXT NOT NULL,
  guests       TEXT NOT NULL,
  status       TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  escalated_at TEXT,
  decided_at   TEXT,
  entered_at   TEXT,
  exited_at    TEXT
);

-- WhatsApp message ids already handled, so a retried message runs once.
CREATE TABLE seen_messages (
  id   TEXT PRIMARY KEY,
  seen TEXT NOT NULL
);

-- The guard sent IN <code> and the app is waiting for the visitor's photo.
-- One row per guard number, so a second IN replaces the first.
CREATE TABLE photo_waits (
  guard     TEXT PRIMARY KEY,
  reference TEXT NOT NULL,
  asked     TEXT NOT NULL
);

-- The photo the guard took at the gate. The picture itself stays in the gate
-- desk's WhatsApp chat. The app keeps Meta's id for it and the time.
CREATE TABLE photos (
  reference TEXT PRIMARY KEY,
  media_id  TEXT NOT NULL,
  taken_at  TEXT NOT NULL
);

-- The codes on the visitor's pass. Each visit has one entry code and one
-- exit code, and each code does only its own job at the gate. The reference
-- stays with the approvers and opens nothing. The primary key keeps every
-- code unique across both kinds, so no exit code can equal an entry code.
CREATE TABLE gate_codes (
  code      TEXT PRIMARY KEY,
  reference TEXT NOT NULL,
  kind      TEXT NOT NULL
);
CREATE INDEX gate_codes_reference ON gate_codes (reference);

-- The escalation sweep, the purge and the open-request list all filter on
-- status and created_at. The admin list pages through visits newest first.
-- reference breaks a tie between two visits made in the same second, so it
-- is in both indexes, and a page starts where the last one ended instead of
-- counting past the rows before it.
CREATE INDEX visits_status_created_ref ON visits (status, created_at, reference);
CREATE INDEX visits_created_ref ON visits (created_at, reference);
-- The gate board's expected list: approved passes by decision time.
CREATE INDEX visits_status_decided ON visits (status, decided_at);
-- The purge deletes old message ids every 30 seconds.
CREATE INDEX seen_messages_seen ON seen_messages (seen);
""",
    # 2: approvers set on the admin page, and auto-approval.
    """
-- Set on the admin page. A reason with no row uses the settings.
CREATE TABLE approvers (
  reason     TEXT PRIMARY KEY,
  main       TEXT NOT NULL,
  backup     TEXT NOT NULL,
  changed_at TEXT NOT NULL
);

-- Empty for a request made outside working hours.
ALTER TABLE visits ADD COLUMN auto_approve_at TEXT;
-- main, backup or auto. Never a phone: the visitor's page shows this row.
ALTER TABLE visits ADD COLUMN decided_by TEXT;
CREATE INDEX visits_status_auto ON visits (status, auto_approve_at);
""",
    # 3: the number that decided, for the admin page only.
    """
-- The approver's number as set when they decided. Empty for an automatic
-- approval and for decisions made before this step.
ALTER TABLE visits ADD COLUMN decided_phone TEXT;
""",
    # 4: guards added on the admin page, and who let each visitor in and out.
    """
-- Each guard has their own gate key. Only its SHA-256 hash is kept.
CREATE TABLE guards (
  phone    TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  added_at TEXT NOT NULL
);

-- The guard's name and number as they were at the gate. Empty before this step.
ALTER TABLE visits ADD COLUMN entered_by TEXT;
ALTER TABLE visits ADD COLUMN exited_by TEXT;
""",
    # 5: the gate page's photo, kept in the database.
    """
-- A photo taken on the gate page. A WhatsApp photo keeps only media_id.
ALTER TABLE photos ADD COLUMN image BYTEA;
-- A gate page photo has no WhatsApp id. This only relaxes a rule, so the old
-- version, which always writes media_id, keeps working while Render deploys.
ALTER TABLE photos ALTER COLUMN media_id DROP NOT NULL;
""",
]

# Advisory lock id, so two starting instances never run a step twice.
MIGRATION_LOCK = 4_022_001

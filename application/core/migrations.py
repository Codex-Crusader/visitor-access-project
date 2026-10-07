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
    # 6: offices with their own approvers, more admins, the allow list and the blacklist.
    """
-- The offices a visitor picks under "See an office". Each has two approvers.
-- tag groups the offices on the admin page and in the visitor's list. Empty is no tag.
CREATE TABLE offices (
  name     TEXT PRIMARY KEY,
  main     TEXT NOT NULL,
  backup   TEXT NOT NULL,
  added_at TEXT NOT NULL,
  tag      TEXT NOT NULL DEFAULT ''
);
-- "Accounts" and "accounts" are one office.
CREATE UNIQUE INDEX offices_name_lower ON offices (lower(name));
-- The office the visitor picked. Empty for other reasons and before this step.
ALTER TABLE visits ADD COLUMN office TEXT;

-- Admins added on the admin page, each with their own key. Only its hash is kept.
-- super: may approve and decline requests in bulk. The main admin is always one.
CREATE TABLE admins (
  phone    TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  key_hash TEXT NOT NULL UNIQUE,
  added_at TEXT NOT NULL,
  super    BOOLEAN NOT NULL DEFAULT FALSE
);

-- The allow list: staff and faculty who enter without a request. A guard sends their 7-digit code.
CREATE TABLE staff (
  code     TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  phone    TEXT NOT NULL UNIQUE,
  added_at TEXT NOT NULL,
  tag      TEXT NOT NULL DEFAULT ''
);

-- Each staff entry. Name, number and guard are kept as they were at the gate.
CREATE TABLE staff_entries (
  id         BIGSERIAL PRIMARY KEY,
  code       TEXT NOT NULL,
  name       TEXT NOT NULL,
  phone      TEXT NOT NULL,
  entered_at TEXT NOT NULL,
  entered_by TEXT NOT NULL
);
CREATE INDEX staff_entries_entered ON staff_entries (entered_at);

-- Numbers that may not request a visit or enter. phone_key is the last 10 digits.
CREATE TABLE blacklist (
  phone_key TEXT PRIMARY KEY,
  phone     TEXT NOT NULL,
  name      TEXT NOT NULL,
  reason    TEXT NOT NULL,
  added_at  TEXT NOT NULL
);

-- Each time the blacklist stopped someone, for the admin page.
CREATE TABLE blocked_attempts (
  id      BIGSERIAL PRIMARY KEY,
  phone   TEXT NOT NULL,
  name    TEXT NOT NULL,
  what    TEXT NOT NULL,
  detail  TEXT NOT NULL,
  by_whom TEXT NOT NULL,
  at      TEXT NOT NULL
);
CREATE INDEX blocked_attempts_at ON blocked_attempts (at);

-- Who changed a list, a number or a key on the admin page or by KEY. Never the key itself.
CREATE TABLE admin_changes (
  id      BIGSERIAL PRIMARY KEY,
  at      TEXT NOT NULL,
  by_whom TEXT NOT NULL,
  action  TEXT NOT NULL,
  detail  TEXT NOT NULL
);
CREATE INDEX admin_changes_at ON admin_changes (at);
""",
    # 7: a resend from the same page returns the first request.
    """
-- A random key from the visitor's browser, one for each filled-in form. A second send
-- with the same key, after a timeout, gets the first request back. Empty before this step.
ALTER TABLE visits ADD COLUMN request_key TEXT;
CREATE UNIQUE INDEX visits_request_key ON visits (request_key) WHERE request_key IS NOT NULL;
""",
    # 8: the blacklist knows each number with its country code, not only its last 10 digits.
    """
-- One key for a phone number, with its country code: 98765 43210, 098765 43210,
-- +91 98765 43210 and 0091 98765 43210 are one number. A number with no country code is
-- Indian. blacklist.number_key() in Python does the same, and a test checks that they agree.
CREATE FUNCTION phone_number_key(phone TEXT) RETURNS TEXT
LANGUAGE SQL IMMUTABLE AS $$
  SELECT CASE
    WHEN d LIKE '00%' THEN substr(d, 3)
    WHEN length(d) = 11 AND d LIKE '0%' THEN '91' || substr(d, 2)
    WHEN length(d) = 10 THEN '91' || d
    ELSE d END
  FROM (SELECT regexp_replace(phone, '[^0-9]', '', 'g') AS d) AS digits
$$;
ALTER TABLE blacklist ADD COLUMN number_key TEXT;
UPDATE blacklist SET number_key = phone_number_key(phone);
-- The old last-10 key stays, so the version before this step still runs, also after a
-- rollback. It is no longer unique: two countries can share the last 10 digits.
ALTER TABLE blacklist DROP CONSTRAINT blacklist_pkey;
CREATE INDEX blacklist_phone_key ON blacklist (phone_key);
CREATE UNIQUE INDEX blacklist_number_key ON blacklist (number_key);
""",
    # 9: the database itself refuses a status, code kind or decider the app does not know.
    """
-- NOT VALID: new and changed rows are checked, old rows are not read, so the step is quick
-- and never fails on a row the app wrote before.
ALTER TABLE visits ADD CONSTRAINT visits_status_known CHECK (status IN
  ('pending', 'escalated', 'approved', 'declined', 'inside', 'closed', 'expired')) NOT VALID;
ALTER TABLE visits ADD CONSTRAINT visits_decided_by_known CHECK (decided_by IS NULL OR
  decided_by IN ('main', 'backup', 'auto', 'admin', 'blacklist')) NOT VALID;
ALTER TABLE gate_codes ADD CONSTRAINT gate_codes_kind_known CHECK (kind IN ('entry', 'exit'))
  NOT VALID;
""",
    # 10: each reason and each office has its own time for automatic approval.
    """
-- Minutes before a working-hours request with no answer is approved by itself.
-- No row, or an empty value, is AUTO_APPROVE_MINUTES. 0 is never.
CREATE TABLE reason_auto (
  reason     TEXT PRIMARY KEY,
  minutes    INTEGER NOT NULL CHECK (minutes >= 0),
  changed_at TEXT NOT NULL
);
ALTER TABLE offices ADD COLUMN auto_minutes INTEGER CHECK (auto_minutes >= 0);
""",
]

# Advisory lock id, so two starting instances never run a step twice.
MIGRATION_LOCK = 4_022_001

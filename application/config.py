"""Settings from the environment, or from a .env file when one exists."""

import json
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is missing from the environment")
    return value


def _int(name, default):
    return int(os.getenv(name, default))


def _flag(name):
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes")


META_TOKEN = _required("META_TOKEN")
META_PHONE_NUMBER_ID = _required("META_PHONE_NUMBER_ID")
META_VERIFY_TOKEN = _required("META_VERIFY_TOKEN")

# Without the App secret, anyone who finds the webhook address can send a
# message that looks like an approver's YES or a guard's IN. So the app does
# not start without it. ALLOW_UNSIGNED_WEBHOOK=true allows that, for a test
# on your own machine only.
ALLOW_UNSIGNED_WEBHOOK = _flag("ALLOW_UNSIGNED_WEBHOOK")
META_APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
if not META_APP_SECRET and not ALLOW_UNSIGNED_WEBHOOK:
    raise RuntimeError(
        "META_APP_SECRET is missing from the environment. Copy the App secret from"
        " the Meta app, under App settings, then Basic. For a test on your own"
        " machine only, set ALLOW_UNSIGNED_WEBHOOK=true instead."
    )

MAIN_APPROVER = _required("MAIN_APPROVER")
BACKUP_APPROVER = os.getenv("BACKUP_APPROVER", "").strip() or MAIN_APPROVER
GUARD = os.getenv("GUARD", "").strip() or MAIN_APPROVER
# Gets the admin key on "Forgot admin key?". The gate key goes to GUARD.
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "").strip() or MAIN_APPROVER

# The reasons the visitor form offers, the same list as REASONS in
# static/app.js. "Other" also covers every reason the visitor typed in.
REASONS = ("See a student", "See an office", "Delivery", "Event", "Other")


def _approvers():
    """Each reason's (main, backup) approver.

    Every reason starts with MAIN_APPROVER and BACKUP_APPROVER. APPROVERS
    changes some of them, as JSON: {"Delivery": ["+91...", "+91..."]}.
    A reason it does not name keeps the two defaults. A wrong name stops the
    start, because a typo would otherwise send that reason to the defaults.
    """
    table = dict.fromkeys(REASONS, (MAIN_APPROVER, BACKUP_APPROVER))
    raw = os.getenv("APPROVERS", "").strip()
    if not raw:
        return table
    example = 'Write it like {"Delivery": ["+91...", "+91..."]}.'
    try:
        given = json.loads(raw)
    except ValueError:
        raise RuntimeError(f"APPROVERS is not valid JSON. {example}") from None
    if not isinstance(given, dict):
        raise RuntimeError(f"APPROVERS must be a JSON object. {example}")
    for reason, numbers in given.items():
        if reason not in table:
            raise RuntimeError(f"APPROVERS names {reason!r}, which is not one of {REASONS}")
        if isinstance(numbers, str):
            numbers = [numbers]
        if not numbers or not str(numbers[0]).strip():
            raise RuntimeError(f"APPROVERS gives no number for {reason!r}")
        main = str(numbers[0]).strip()
        backup = str(numbers[1]).strip() if len(numbers) > 1 else main
        table[reason] = (main, backup)
    return table


# Defaults. The admin page can replace them, see people.approver_table.
APPROVERS = _approvers()

KEY_LENGTH = 20
MAKE_KEY = 'python -c "import secrets; print(secrets.token_urlsafe(24))"'


def key_problem(name, key):
    """Why a key is not safe to use, or "" when it is."""
    if len(key) < KEY_LENGTH:
        return f"{name} must be {KEY_LENGTH} characters or more. Make one with: {MAKE_KEY}"
    if "change-me" in key.lower():
        return f"{name} is still the example from .env.example. Make one with: {MAKE_KEY}"
    return ""


# The guard types this on the gate page. Entry and exit need it.
GATE_KEY = _required("GATE_KEY")
if key_problem("GATE_KEY", GATE_KEY):
    raise RuntimeError(key_problem("GATE_KEY", GATE_KEY))


def read_admin_key():
    """(key, why locked). The admin page's own key.

    Every guard holds the gate key, so the gate key never opens the admin
    list. Without a key of its own the admin page stays locked, and the rest
    of the app runs as usual.
    """
    key = os.getenv("ADMIN_KEY", "").strip()
    if not key:
        return "", "The admin page is locked until ADMIN_KEY is set on the server."
    if key == GATE_KEY:
        return "", ("The admin page is locked: ADMIN_KEY must differ from GATE_KEY,"
                    " because every guard holds the gate key.")
    problem = key_problem("ADMIN_KEY", key)
    if problem:
        return "", f"The admin page is locked: {problem}"
    return key, ""


ADMIN_KEY, ADMIN_LOCKED = read_admin_key()

GATE_DESK_PHONE = _required("GATE_DESK_PHONE")

# The approved WhatsApp template for the approval request. WhatsApp delivers
# plain text only within 24 hours of the approver's last message, and drops it
# quietly after that, so the request goes out as this template. Set it empty to
# send plain text only.
REQUEST_TEMPLATE = os.getenv("REQUEST_TEMPLATE", "visit_request").strip()
TEMPLATE_LANGUAGE = os.getenv("TEMPLATE_LANGUAGE", "en").strip()
# When Meta refuses the template, send plain text instead. Turn this on only
# while Meta reviews a new template. In production, it hides a paused or
# disabled template: plain text is lost for a quiet approver, and the visitor
# is told the request went out. Off, the visitor is told it failed.
TEMPLATE_FALLBACK = _flag("TEMPLATE_FALLBACK")
ESCALATE_MINUTES = _int("ESCALATE_MINUTES", 15)

# Auto-approve a working-hours request after this many minutes. 0 = off.
AUTO_APPROVE_MINUTES = _int("AUTO_APPROVE_MINUTES", 30)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _hours():
    """WORK_HOURS such as 10-17, as (10, 17)."""
    raw = os.getenv("WORK_HOURS", "10-17").strip()
    try:
        start, end = (int(part) for part in raw.split("-"))
    except ValueError:
        raise RuntimeError(f"WORK_HOURS must look like 10-17, not {raw!r}") from None
    if not 0 <= start < end <= 24:
        raise RuntimeError(f"WORK_HOURS {raw!r} must start before it ends, within 0-24")
    return start, end


def _days():
    """WORK_DAYS such as Mon,Tue, as day numbers with Monday 0."""
    raw = os.getenv("WORK_DAYS", "Mon,Tue,Wed,Thu,Fri,Sat")
    names = [name.strip().title() for name in raw.split(",") if name.strip()]
    wrong = [name for name in names if name not in WEEKDAYS]
    if wrong or not names:
        raise RuntimeError(f"WORK_DAYS must list days from {WEEKDAYS}, not {raw!r}")
    return frozenset(WEEKDAYS.index(name) for name in names)


# 10:00 is inside working hours, 17:00 is outside.
WORK_START, WORK_END = _hours()
WORK_DAYS = _days()
WORK_TIMEZONE = ZoneInfo(os.getenv("WORK_TIMEZONE", "Asia/Kolkata").strip())

# Days a visit record is kept. The privacy screen states this number.
RETAIN_DAYS = _int("RETAIN_DAYS", 90)

# A pass lets its visitor in for this many hours after the request. A visitor
# already inside can always leave.
PASS_HOURS = _int("PASS_HOURS", 48)

# How many new requests one address may send per hour. The web address is
# public, so this stops a stranger making the approver's phone ring all night.
# Counted per IP address. People on one campus Wi-Fi share an address, so this
# has to be generous enough for a whole group, not one person.
REQUESTS_PER_HOUR = _int("REQUESTS_PER_HOUR", 60)
# True when a proxy such as Render sits in front and sets True-Client-IP or
# X-Forwarded-For, see limits.caller(). Leave it false on your own machine,
# where nothing sets those headers and trusting them would let anyone fake
# their address.
BEHIND_PROXY = _flag("BEHIND_PROXY")

# The Postgres connection string, such as Neon's. Visits live there, so they
# stay when Render deploys a new version. It holds the database password: keep it out of git.
DATABASE_URL = _required("DATABASE_URL")

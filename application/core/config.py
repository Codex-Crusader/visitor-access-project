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

# No App secret means anyone can fake a YES. ALLOW_UNSIGNED_WEBHOOK=true is for local tests.
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
ADMIN_PHONE_SET = bool(os.getenv("ADMIN_PHONE", "").strip())

# Same list as REASONS in static/visitor.js. "Other" also covers typed-in reasons.
REASONS = ("See a student", "See an office", "Delivery", "Event", "Other")
# With this reason the visitor picks an office, which has its own approvers.
OFFICE_REASON = "See an office"


def _approvers():
    """Each reason's (main, backup). APPROVERS overrides some; an unknown reason stops the start."""
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
    for reason, value in given.items():
        if reason not in table:
            raise RuntimeError(f"APPROVERS names {reason!r}, which is not one of {REASONS}")
        numbers = [value] if isinstance(value, str) else value
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
    """(key, why locked). Locked without its own key, because every guard holds the gate key."""
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

# The approval request template. Plain text reaches only approvers active in the last 24 h.
REQUEST_TEMPLATE = os.getenv("REQUEST_TEMPLATE", "visit_request").strip()
TEMPLATE_LANGUAGE = os.getenv("TEMPLATE_LANGUAGE", "en").strip()
# Plain text when Meta refuses the template. Only while Meta reviews one: it hides failures.
TEMPLATE_FALLBACK = _flag("TEMPLATE_FALLBACK")
ESCALATE_MINUTES = _int("ESCALATE_MINUTES", 15)
# The staff entry message. Empty sends plain text, which reaches only staff active in the last 24 h.
STAFF_ENTRY_TEMPLATE = os.getenv("STAFF_ENTRY_TEMPLATE", "").strip()

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

# Hours a pass lets its visitor in. A visitor inside can always leave.
PASS_HOURS = _int("PASS_HOURS", 48)

# New requests per address per hour. Generous, because one campus Wi-Fi is one address.
REQUESTS_PER_HOUR = _int("REQUESTS_PER_HOUR", 60)
# All new requests in one hour, from every address together. Each one sends a WhatsApp
# template, so this caps the messages to approvers and Meta's charges when many addresses
# send at once. A campus event needs a higher number.
REQUESTS_PER_HOUR_ALL = _int("REQUESTS_PER_HOUR_ALL", 300)
# True behind Render's proxies, see limits.caller(). False locally, or anyone can fake an address.
BEHIND_PROXY = _flag("BEHIND_PROXY")
# The one header the proxy sets to the visitor's address. Empty: True-Client-IP with BEHIND_PROXY.
CLIENT_IP_HEADER = os.getenv("CLIENT_IP_HEADER", "").strip()

# Neon Postgres. Holds the database password: keep it out of git.
DATABASE_URL = _required("DATABASE_URL")

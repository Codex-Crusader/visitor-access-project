"""Settings from the environment, or from a .env file when one exists."""

import json
import os

from dotenv import load_dotenv

load_dotenv()


def _required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is missing from the environment")
    return value


def _int(name, default):
    return int(os.getenv(name, default))


META_TOKEN = _required("META_TOKEN")
META_PHONE_NUMBER_ID = _required("META_PHONE_NUMBER_ID")
META_VERIFY_TOKEN = _required("META_VERIFY_TOKEN")
META_APP_SECRET = os.getenv("META_APP_SECRET", "").strip()

MAIN_APPROVER = _required("MAIN_APPROVER")
BACKUP_APPROVER = os.getenv("BACKUP_APPROVER", "").strip() or MAIN_APPROVER
GUARD = os.getenv("GUARD", "").strip() or MAIN_APPROVER

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
    for reason, numbers in json.loads(raw).items():
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


APPROVERS = _approvers()


def approvers_for(reason):
    """(main, backup) for a visit's reason. A typed-in reason counts as the reason Other."""
    return APPROVERS.get(reason, APPROVERS["Other"])

# The guard types this on the gate page. Entry and exit need it.
GATE_KEY = _required("GATE_KEY")


def read_admin_key():
    """The admin page's own key. Every guard holds the gate key, so the gate
    key must not open the admin list, and the app will not start with it."""
    key = _required("ADMIN_KEY")
    if key == GATE_KEY:
        raise RuntimeError(
            "ADMIN_KEY must differ from GATE_KEY, or every guard can open the admin page"
        )
    return key


ADMIN_KEY = read_admin_key()

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
TEMPLATE_FALLBACK = os.getenv("TEMPLATE_FALLBACK", "").strip().lower() in ("1", "true", "yes")
ESCALATE_MINUTES = _int("ESCALATE_MINUTES", 15)

# Days a visit record is kept. The privacy screen states this number.
RETAIN_DAYS = _int("RETAIN_DAYS", 90)

# How many new requests one address may send per hour. The web address is
# public, so this stops a stranger making the approver's phone ring all night.
# Counted per IP address. People on one campus Wi-Fi share an address, so this
# has to be generous enough for a whole group, not one person.
REQUESTS_PER_HOUR = _int("REQUESTS_PER_HOUR", 60)
# True when a proxy such as Render sits in front and sets X-Forwarded-For.
# Leave it false on your own machine, where nothing sets that header and
# trusting it would let anyone fake their address.
BEHIND_PROXY = os.getenv("BEHIND_PROXY", "").strip().lower() in ("1", "true", "yes")

DATABASE_PATH = os.getenv("DATABASE_PATH", "visits.db")

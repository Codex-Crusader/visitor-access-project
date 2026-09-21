"""Settings from the environment, or from a .env file when one exists."""

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

# The guard types this on the gate page. Entry and exit need it.
GATE_KEY = _required("GATE_KEY")

GATE_DESK_PHONE = _required("GATE_DESK_PHONE")
ESCALATE_MINUTES = _int("ESCALATE_MINUTES", 30)

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

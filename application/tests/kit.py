"""What every test file shares: the settings, a clean database, WhatsApp stubbed, the client
and the helpers. A test file imports it first, so the settings are in place before the app."""

import base64
import csv as _csv
import io
import os
import re
import sys
from pathlib import Path

import psycopg
from PIL import Image

# The app's modules are one folder up.
APP_DIR = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, APP_DIR)

import testdb

os.environ.update(
    META_TOKEN="test-token",
    META_PHONE_NUMBER_ID="100000000000000",
    META_VERIFY_TOKEN="visitor-access-verify",
    META_APP_SECRET="",
    ALLOW_UNSIGNED_WEBHOOK="true",
    MAIN_APPROVER="+911234567890",
    BACKUP_APPROVER="+911234567890",
    GUARD="+911234567890",
    ADMIN_PHONE="+911234567899",
    GATE_KEY="test-gate-key-long-enough",
    ADMIN_KEY="test-admin-key-long-enough",
    GATE_DESK_PHONE="+912200000000",
    ESCALATE_MINUTES="30",
    RETAIN_DAYS="1",
    DATABASE_URL=testdb.url(),
)

# Each test file starts on an empty database. On GitHub all files share one Postgres.
with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as fresh:
    fresh.execute("DROP SCHEMA public CASCADE")
    fresh.execute("CREATE SCHEMA public")

import app as application
from core import db
from core import checks
from models import visits
from services import whatsapp

sent = []
whatsapp.send = lambda to, body: sent.append((to, body))
# A template arrives as its values, one per line, so the checks below can read it.
templates = []


# noinspection PyShadowingNames,PyUnusedLocal
def fake_template(to, values, name=None):
    templates.append((to, values))
    sent.append((to, "\n".join(values)))


whatsapp.send_template = fake_template

db.init()
# The cache works from the first call, so every check below runs through it.
db.CACHE_AFTER_SECONDS = 0
client = application.app.test_client()
GATE_KEY_TEXT, ADMIN_KEY_TEXT = "test-gate-key-long-enough", "test-admin-key-long-enough"
KEY = {"X-Gate-Key": GATE_KEY_TEXT}
ADMIN = {"X-Admin-Key": ADMIN_KEY_TEXT}


def jpeg(width=64, height=48, exif=None):
    """A real JPEG, as the gate page sends it. The server decodes every photo."""
    out = io.BytesIO()
    extra = {"exif": exif} if exif else {}
    Image.new("RGB", (width, height), (120, 90, 160)).save(out, "JPEG", **extra)
    return out.getvalue()


def as_photo(data):
    return {"photo": checks.PHOTO_PREFIX + base64.b64encode(data).decode()}


def is_clean_photo(data):
    """True for a JPEG the server redrew: the same size, and no metadata."""
    with Image.open(io.BytesIO(data)) as decoded:
        return decoded.format == "JPEG" and decoded.size == (64, 48) and not decoded.getexif()


JPEG = jpeg()
PHOTO = as_photo(JPEG)
# A gate code: two letters without I or O, a dash, four digits.
GATE_CODE = re.compile(r"^[A-HJ-NP-Z]{2}-\d{4}$")


def entry_of(ticket):
    """The entry code. The server and the visitor's pass are the only holders."""
    return visits.codes_of(ticket["reference"])["entry"]


def exit_of(ticket):
    return visits.codes_of(ticket["reference"])["exit"]


counter = [0]


def inbound(sender, text):
    """Build a Meta webhook payload with a fresh message id."""
    counter[0] += 1
    return {
        "entry": [{"changes": [{"value": {"messages": [
            {"id": f"wamid.{counter[0]}", "from": sender, "type": "text",
             "text": {"body": text}}
        ]}}]}]
    }


def say(sender, text):
    client.post("/webhook/whatsapp", json=inbound(sender, text))
    return sent[-1][1] if sent else ""


def picture(sender, caption=None):
    """Build a Meta webhook payload for a photo, with a fresh message id."""
    counter[0] += 1
    image = {"id": f"media.{counter[0]}", "mime_type": "image/jpeg"}
    if caption is not None:
        image["caption"] = caption
    return {
        "entry": [{"changes": [{"value": {"messages": [
            {"id": f"wamid.{counter[0]}", "from": sender, "type": "image", "image": image}
        ]}}]}]
    }


def snap(sender):
    """The guard sends a photo. Returns the reply, or "" when there was none."""
    count_at_start = len(sent)
    client.post("/webhook/whatsapp", json=picture(sender))
    return sent[-1][1] if len(sent) > count_at_start else ""


payload = {
    "name": "Asha Rao",
    "phone": "9876543210",
    "address": "12 Park Road, Karjat",
    "reason": "See a student",
    "visiting": "2024SEPVUGP0003",
    "guests": ["Ravi Rao"],
}

APPROVER = "911234567890"
STRANGER = "910000000000"


def new_request():
    created = client.post("/api/requests", json=payload)
    assert created.status_code == 201, created.get_data(as_text=True)
    return created.get_json()


def refused(*_args):
    raise whatsapp.Refused("WhatsApp send failed (404): template name does not exist")


def approved():
    ticket = new_request()
    say(APPROVER, f"YES {ticket['reference']}")
    return ticket


def status_of(ticket):
    return client.get(f"/api/visit/{ticket['token']}").get_json()["status"]


def broken(*_args):
    raise RuntimeError("database is locked")


def csv_rows(text):
    """The rows of a CSV the app made. It starts with the UTF-8 mark, for Excel."""
    assert text.startswith("﻿"), "Excel needs the mark to read every letter"
    return list(_csv.DictReader(io.StringIO(text[1:])))


def add_admin(admin_name, admin_phone, with_key=None):
    return client.post("/api/admin/admins", json={"name": admin_name, "phone": admin_phone},
                       headers=with_key or ADMIN)


def add_staff(staff_name, staff_phone, with_key=None):
    return client.post("/api/admin/staff", json={"name": staff_name, "phone": staff_phone},
                       headers=with_key or ADMIN)


def add_black(black_phone, black_name="Kiran", reason="Damaged property", with_key=None):
    return client.post("/api/admin/blacklist", headers=with_key or ADMIN,
                       json={"phone": black_phone, "name": black_name, "reason": reason})


def older():
    """Moves every blocked attempt 11 minutes back, past the repeat window."""
    with db.connect() as writer:
        writer.execute("UPDATE blocked_attempts SET at = %s", (db.ago(11 / 1440),))


# The visit reads as made this many hours ago.
def made_hours_ago(ticket, hours):
    with db.connect() as db_conn:
        db_conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                        (db.ago(hours / 24), ticket["reference"]))
    db.forget_cache()


def finish():
    """Ends a test file: the timer stops and the pool closes, before Python shuts down."""
    application.stop_background()
    print()
    print("all checks passed")


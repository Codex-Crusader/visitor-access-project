"""End to end check with the WhatsApp call stubbed out.

Run it with: .venv\\Scripts\\python.exe test_app.py
It sends no WhatsApp messages and uses a throwaway database.
"""

import ast
import base64
import contextlib
import io
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import psycopg
from PIL import Image
from psycopg_pool import PoolTimeout

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

import app as application
import config
import db
import access
from routes import admin as admin_routes
import checks
import limits
import pages
import timer
from routes import webhook as webhook_routes
import entries
import migrations
import people
import visits
import whatsapp

sent = []
whatsapp.send = lambda to, body: sent.append((to, body))
# A template arrives as its values, one per line, so the checks below can read it.
templates = []


def fake_template(to, values):
    templates.append((to, values))
    sent.append((to, "\n".join(values)))


whatsapp.send_template = fake_template

db.init()
# The cache works from the first call, so every check below runs through it.
db.CACHE_AFTER_SECONDS = 0
client =application.app.test_client()
GATE_KEY_TEXT, ADMIN_KEY_TEXT = "test-gate-key-long-enough", "test-admin-key-long-enough"
KEY = {"X-Gate-Key": GATE_KEY_TEXT}
ADMIN = {"X-Admin-Key": "test-admin-key-long-enough"}
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
    replies = len(sent)
    client.post("/webhook/whatsapp", json=picture(sender))
    return sent[-1][1] if len(sent) > replies else ""


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


print("visitor flow")
visit = new_request()
code, token = visit["reference"], visit["token"]
assert visit["status"] == "pending"
assert len(token) > 16, "token must be long enough to resist guessing"
assert code in sent[-1][1]
assert re.fullmatch(r"VR-\d{5}", code), "a new reference has five digits"
print("  created", code)

print("the approval request goes out as a template")
# Plain text reaches the approver only within 24 hours of their last message.
# The template arrives at any time, so the request must use it.
approver, fields = templates[-1]
assert approver == "+911234567890", approver
assert len(fields) == 8, fields
assert fields[0] == code and fields[2] == "Asha Rao" and fields[7] == "Ravi Rao", fields
# Meta refuses an empty value and a line break inside a value.
assert all(v and "\n" not in v for v in fields), fields
assert client.post("/api/requests", json={**payload, "guests": []}).status_code == 201
assert templates[-1][1][7] == "No one", templates[-1][1]

caught = []


class Catch(logging.Handler):
    def emit(self, record):
        caught.append(record.getMessage())


application.app.logger.addHandler(Catch())

real_template = whatsapp.send_template


def refused(*_args):
    raise RuntimeError("WhatsApp send failed (404): template name does not exist")


whatsapp.send_template = refused
try:
    # By default, a refused template is a failed request. Plain text would be
    # lost for a quiet approver while the visitor was told it went out.
    assert application.config.TEMPLATE_FALLBACK is False
    sent_before = len(sent)
    timer.wake.clear()
    refused_request = client.post("/api/requests", json=payload)
    assert not timer.wake.is_set(), "a failed request brings no deadline"
    assert refused_request.status_code == 502, refused_request.status_code
    assert len(sent) == sent_before, "no plain text may go out without the fallback"

    # The backup approver's round fails the same way, and one failure stops
    # neither the other escalations nor the purge after them.
    # An hour old: due for the backup, and not yet expired.
    hour_ago = db.ago(1 / 24)
    with db.connect() as conn:
        conn.execute("UPDATE visits SET created_at = %s WHERE status = 'pending'",
                     (hour_ago,))
    db.forget_cache()
    caught.clear()
    timer.escalate_due()
    assert any("backup approver" in line for line in caught), caught
    assert visits.due_for_escalation(), "a failed escalation must stay due and be tried again"
    with db.connect() as conn:
        conn.execute("UPDATE visits SET created_at = %s WHERE created_at = %s",
                     (db.now(), hour_ago))
    db.forget_cache()

    # While Meta reviews the template, TEMPLATE_FALLBACK sends plain text
    # instead, and the log says so, because plain text alone can be lost.
    application.config.TEMPLATE_FALLBACK = True
    fallback = client.post("/api/requests", json=payload)
    assert fallback.status_code == 201, fallback.get_data(as_text=True)
    assert f"Reply YES {fallback.get_json()['reference']}" in sent[-1][1]
    assert any("template refused" in line for line in caught), caught

    # When plain text fails too, the visitor is told, and nothing is kept.
    real_send = whatsapp.send

    def down(*_args):
        raise RuntimeError("WhatsApp send failed (500)")

    whatsapp.send = down
    try:
        lost = client.post("/api/requests", json=payload)
        assert lost.status_code == 502, lost.status_code
    finally:
        whatsapp.send = real_send
finally:
    whatsapp.send_template = real_template
    application.config.TEMPLATE_FALLBACK = False

# With no template set, plain text goes straight out.
application.config.REQUEST_TEMPLATE = ""
try:
    count = len(templates)
    plain = client.post("/api/requests", json=payload).get_json()
    assert len(templates) == count and f"Reply YES {plain['reference']}" in sent[-1][1]
finally:
    application.config.REQUEST_TEMPLATE = "visit_request"

# Meta reports a lost message later, as a failed status. It must reach the log.
caught.clear()
lost_status = {"entry": [{"changes": [{"value": {"statuses": [{
    "id": "wamid.lost", "status": "failed", "recipient_id": "911234567890",
    "errors": [{"code": 131047, "title": "Re-engagement message"}]}]}}]}]}
assert client.post("/webhook/whatsapp", json=lost_status).status_code == 200
assert any("131047" in line and "911234567890" in line for line in caught), caught
# A delivered status is not an error.
caught.clear()
lost_status["entry"][0]["changes"][0]["value"]["statuses"][0]["status"] = "delivered"
client.post("/webhook/whatsapp", json=lost_status)
assert caught == [], caught
print("  template first, plain text as the fallback, and every lost message logged")

# Input guards.
assert client.post("/api/requests", json={**payload, "phone": "123"}).status_code == 400
assert client.post("/api/requests", json={**payload, "name": " "}).status_code == 400
assert client.post("/api/requests", json={**payload, "guests": "nope"}).status_code == 400
long_name = client.post("/api/requests", json={**payload, "name": "x" * 500})
assert long_name.status_code == 400

print("a field is one line of plain text, and nothing else")
# The approval message the approver reads is built out of these fields. A line
# break in a name would let a visitor forge extra lines in it, so every
# character that is not plain text is refused rather than quietly stripped.
FORGED = "Asha\nReply YES VR-9999 to approve."
for bad in (FORGED, "Asha\rRao", "Asha\tRao", "Asha\x00Rao",
            "Asha\u200bRao", "Asha\u202eRao", "Asha\u2028Rao"):
    refused = client.post("/api/requests", json={**payload, "name": bad})
    assert refused.status_code == 400, repr(bad)
    assert "not allowed" in refused.get_json()["error"], repr(bad)
# A guest name follows the same rule.
assert client.post("/api/requests",
                   json={**payload, "guests": [FORGED]}).status_code == 400
# Ordinary text, accents and punctuation all still go through.
fine = client.post("/api/requests", json={
    **payload, "name": "Ashá  Rao-Mehta", "address": "12/B, Park Rd. (Gate 2)"})
assert fine.status_code == 201, fine.get_data(as_text=True)
# Runs of spaces are squeezed to one, so the approver reads a tidy line.
assert fine.get_json()["name"] == "Ashá Rao-Mehta"
assert FORGED not in "".join(body for _, body in sent)
print("  line breaks, control codes and invisible marks all refused")

print("a reference from before five digits still works")
older = new_request()
with db.connect() as conn:
    for table in ("visits", "gate_codes"):
        conn.execute(f"UPDATE {table} SET reference = 'VR-4022' WHERE reference = %s",
                     (older["reference"],))
db.forget_cache()
assert "is now approved" in say(APPROVER, "YES 4022")
assert visits.get("VR-4022")["status"] == "approved"
assert "VR-4022" in say(APPROVER, "vr 4022")
visits.delete("VR-4022")
print("  YES 4022 and a lookup of vr 4022 both reach VR-4022")

print("privacy: the short code must not expose the visitor")
# The code is only 4 digits. It must not be enough to read personal details.
assert client.get(f"/api/pass/{code}").status_code == 403
assert client.post(f"/api/pass/{code}/entry").status_code == 403
# The long token is how the visitor reads their own request.
mine = client.get(f"/api/visit/{token}")
assert mine.status_code == 200 and mine.get_json()["name"] == "Asha Rao"
assert client.get("/api/visit/not-a-real-token").status_code == 404

print("each pass has its own entry code and exit code")
entry_code, exit_code = entry_of(visit), exit_of(visit)
assert GATE_CODE.match(entry_code) and GATE_CODE.match(exit_code), (entry_code, exit_code)
assert entry_code != exit_code
# The reference is for approvers. It opens nothing, so it never looks like a gate code.
assert code.startswith("VR-")
# The letters change from pass to pass, not only the digits.
limits.forget_hits()
letters = {entry_of(new_request())[:2] for _ in range(12)}
limits.forget_hits()
assert len(letters) > 1, letters
# The generator itself: 2000 codes, no I or O to misread as 1 or 0, never VR.
made_codes = [visits.new_gate_code() for _ in range(2000)]
assert all(GATE_CODE.match(c) and not c.startswith("VR") for c in made_codes)
assert len({c[:2] for c in made_codes}) > 400, "the letters must vary widely"
# The visitor sees no code while the request waits for a decision.
waiting_view = client.get(f"/api/visit/{token}").get_json()
assert "entry_code" not in waiting_view and "exit_code" not in waiting_view
# The response to the request itself carries no code either.
assert entry_code not in str(visit) and exit_code not in str(visit)

print("webhook verification")
ok = client.get("/webhook/whatsapp", query_string={
    "hub.mode": "subscribe", "hub.verify_token": "visitor-access-verify",
    "hub.challenge": "12345"})
assert ok.status_code == 200 and ok.get_data(as_text=True) == "12345"
assert client.get("/webhook/whatsapp", query_string={
    "hub.mode": "subscribe", "hub.verify_token": "wrong"}).status_code == 403

print("whatsapp replies")
sent.clear()
client.post("/webhook/whatsapp", json=inbound(STRANGER, "YES"))
assert sent == [], "a stranger must get no reply at all"
polled = client.get(f"/api/visit/{token}")
assert polled.get_json()["status"] == "pending"
# The phone polls with the tag it got. An unchanged pass answers 304, empty.
assert polled.headers["Cache-Control"] == "private, no-cache" and polled.headers["ETag"]
unchanged = client.get(f"/api/visit/{token}", headers={"If-None-Match": polled.headers["ETag"]})
assert unchanged.status_code == 304 and not unchanged.data
assert "ETag" not in client.get("/api/visit/not-a-token").headers, "a 404 carries no tag"

# Unrecognised text returns the waiting request in full, details and all.
guidance = say(APPROVER, "hello")
assert "Asha Rao" in guidance and "2024SEPVUGP0003" in guidance

# Meta re-delivering the same message must not act twice.
repeat = inbound(APPROVER, f"YES {code}")
client.post("/webhook/whatsapp", json=repeat)
before = len(sent)
client.post("/webhook/whatsapp", json=repeat)
assert len(sent) == before, "a repeated message id must be ignored"
assert client.get(f"/api/visit/{token}").get_json()["status"] == "approved"
changed = client.get(f"/api/visit/{token}", headers={"If-None-Match": polled.headers["ETag"]})
assert changed.status_code == 200, "a changed pass sends the new answer"
print("  duplicate delivery ignored, an unchanged poll costs a 304")

assert "already approved" in say(APPROVER, f"NO {code}")
# The other way round: a YES after a NO changes nothing either.
turned_down = new_request()
assert "is now declined" in say(APPROVER, f"NO {turned_down['reference']}")
assert "already declined" in say(APPROVER, f"YES {turned_down['reference']}")
assert visits.get(turned_down["reference"])["status"] == "declined"
# Once approved, the visitor's pass shows the entry code, and only that one.
approved_view = client.get(f"/api/visit/{token}").get_json()
assert approved_view["entry_code"] == entry_code, approved_view
assert "exit_code" not in approved_view and exit_code not in str(approved_view)

print("gate over whatsapp")
# A bare reference is a lookup. It shows the visitor and neither code.
looked = say(APPROVER, code)
assert "Approved" in looked and "Asha Rao" in looked
assert entry_code not in looked and exit_code not in looked, looked
assert say(APPROVER, code.lower().replace("vr-", "")).count("Asha Rao") == 1
# The entry code looks the pass up too, typed any way, and says to use it with IN.
by_entry = say(APPROVER, entry_code.lower().replace("-", " "))
assert f"IN {entry_code}" in by_entry and exit_code not in by_entry, by_entry

# Up to here nobody typed the exit code, so no message may hold it.
assert not any(exit_code in body for _, body in sent)
# OUT before IN is refused.
assert "Not checked in" in say(APPROVER, f"OUT {exit_code}")
# Neither the reference nor the exit code lets anyone in.
assert "No pass has entry code" in say(APPROVER, f"IN {code}")
assert "exit code" in say(APPROVER, f"IN {exit_code}")
assert client.get(f"/api/visit/{token}").get_json()["status"] == "approved"
# A photo with no IN before it lets nobody in.
assert "No entry is waiting" in snap(APPROVER)
# IN only asks for the photo, and names the person to photograph.
asked = say(APPROVER, f"IN {entry_code.lower()}")
assert "Take a photo of Asha Rao" in asked and entry_code in asked, asked
assert client.get(f"/api/visit/{token}").get_json()["status"] == "approved"
# The photo lets them in. The reply cannot hold the exit code: the guard has
# not seen it yet, and only the visitor's pass shows it.
went_in_reply = snap(APPROVER)
assert "Inside now" in went_in_reply and exit_code not in went_in_reply, went_in_reply
entered = client.get(f"/api/visit/{token}").get_json()
assert entered["status"] == "inside" and entered["entered_at"]
assert entries.photo_of(code)["taken_at"] == entered["entered_at"]
# Inside, the visitor's pass swaps the entry code for the exit code.
assert entered["exit_code"] == exit_code and "entry_code" not in entered, entered
# No approval message carried either code.
assert not any(c in value for _, values in templates for value in values
               for c in (entry_code, exit_code))
# A second photo on the same IN lets nobody else in, and a second IN is refused.
assert "No entry is waiting" in snap(APPROVER)
assert "Already inside" in say(APPROVER, f"IN {entry_code}")
# The entry code never records the exit.
assert "entry code" in say(APPROVER, f"OUT {entry_code}")
assert client.get(f"/api/visit/{token}").get_json()["status"] == "inside"
# The OUT command with the exit code closes it. After that, both codes are dead.
assert "Closed" in say(APPROVER, f"OUT {exit_code}")
closed_view = client.get(f"/api/visit/{token}").get_json()
assert closed_view["status"] == "closed"
assert "entry_code" not in closed_view and "exit_code" not in closed_view
assert "closed" in say(APPROVER, f"IN {entry_code}").lower()
assert "No pass has entry code ZZ-0000" in say(APPROVER, "IN ZZ-0000")
assert "Add the entry code" in say(APPROVER, "IN")
assert "Add the exit code" in say(APPROVER, "OUT")
print("  lookup, entry, exit and decommission all correct, each with its own code")

print("the gate photo")


def approved():
    ticket = new_request()
    say(APPROVER, f"YES {ticket['reference']}")
    return ticket


def status_of(ticket):
    return client.get(f"/api/visit/{ticket['token']}").get_json()["status"]


# Two INs in a row: the photo goes to the second, and the reply says which.
first, second_in = approved(), approved()
say(APPROVER, f"IN {entry_of(first)}")
say(APPROVER, f"IN {entry_of(second_in)}")
went_in = snap(APPROVER)
assert second_in["reference"] in went_in and "Inside now" in went_in, went_in
assert status_of(first) == "approved" and status_of(second_in) == "inside"

# An IN older than the time limit is dead. The photo must not let anyone in.
say(APPROVER, f"IN {entry_of(first)}")
with db.connect() as conn:
    conn.execute("UPDATE photo_waits SET asked = %s", ("2020-01-01T00:00:00+00:00",))
db.forget_cache()
late = snap(APPROVER)
assert "No entry is waiting" in late and str(webhook_routes.PHOTO_MINUTES) in late, late
assert status_of(first) == "approved"

# The web gate let the visitor in while the guard was taking the photo.
say(APPROVER, f"IN {entry_of(first)}")
client.post(f"/api/pass/{entry_of(first)}/entry", headers=KEY, json=PHOTO)
assert "Already inside" in snap(APPROVER)
gate_shot = entries.photo_of(first["reference"])
assert is_clean_photo(gate_shot["image"]) and gate_shot["media_id"] is None, \
    "a late photo changes nothing"

# A photo from a stranger gets no answer and changes nothing.
third = approved()
say(APPROVER, f"IN {entry_of(third)}")
assert snap(STRANGER) == ""
assert status_of(third) == "approved"

# An approver who is not the gate desk cannot let anyone in with a photo.
real_guard = application.config.GUARD
application.config.GUARD = "+919999999999"
try:
    assert "Only a guard" in snap(APPROVER)
finally:
    application.config.GUARD = real_guard

# A failure after the message id is spent asks for the photo again, and the
# photo sent again then works, because nothing was used up.
real_enter = entries.enter_with_photo


def broken(*_args):
    raise RuntimeError("database is locked")


entries.enter_with_photo = broken
try:
    assert "Send that again" in snap(APPROVER)
finally:
    entries.enter_with_photo = real_enter
assert status_of(third) == "approved"
assert "Inside now" in snap(APPROVER)
assert status_of(third) == "inside"
print("  IN asks for a photo, and only the photo lets the visitor in")

print("gate over the web page")
second = new_request()
say(APPROVER, f"YES {second['reference']}")
ref2, entry2, exit2 = second["reference"], entry_of(second), exit_of(second)
# The reference opens the details, which is what a tap on the board does.
# It says which code it was, so the page knows whether to offer a button.
by_reference = client.get(f"/api/pass/{ref2.lower()}", headers=KEY)
assert by_reference.status_code == 200 and "code_kind" not in by_reference.get_json()
assert entry2 not in by_reference.get_data(as_text=True)
assert exit2 not in by_reference.get_data(as_text=True)
typed = client.get(f"/api/pass/{entry2.lower().replace('-', '')}", headers=KEY).get_json()
assert typed["code_kind"] == "entry" and typed["code"] == entry2, typed
assert exit2 not in str(typed)
# Only the entry code records the entry, and only the exit code the exit.
assert client.post(f"/api/pass/{ref2}/entry", headers=KEY, json=PHOTO).status_code == 404
wrong_kind = client.post(f"/api/pass/{exit2}/entry", headers=KEY, json=PHOTO)
assert wrong_kind.status_code == 409 and "exit code" in wrong_kind.get_json()["error"]
assert client.post(f"/api/pass/{exit2}/exit", headers=KEY).status_code == 409
entered = client.post(f"/api/pass/{entry2}/entry", headers=KEY, json=PHOTO)
assert entered.status_code == 200 and entered.get_json()["status"] == "inside"
assert exit2 not in entered.get_data(as_text=True)
assert client.post(f"/api/pass/{entry2}/entry", headers=KEY, json=PHOTO).status_code == 409
assert client.post(f"/api/pass/{ref2}/exit", headers=KEY).status_code == 404
wrong_kind = client.post(f"/api/pass/{entry2}/exit", headers=KEY)
assert wrong_kind.status_code == 409 and "entry code" in wrong_kind.get_json()["error"]
left = client.post(f"/api/pass/{exit2}/exit", headers=KEY)
assert left.status_code == 200 and left.get_json()["status"] == "closed"
for dead_code, action in ((entry2, "entry"), (exit2, "exit")):
    dead = client.post(f"/api/pass/{dead_code}/{action}", headers=KEY)
    assert dead.status_code == 409 and "closed" in dead.get_json()["error"]

print("a closed pass stops showing the visitor")
# The privacy screen promises the gate desk sees the details while the visit
# is open. Once the visitor has left, the code answers with times and nothing
# personal. The CSV export still holds the whole log.
PERSONAL = ("name", "phone", "address", "reason", "visiting")
gone = client.get(f"/api/pass/{ref2}", headers=KEY)
assert gone.status_code == 200
shut = gone.get_json()
assert shut["status"] == "closed"
assert shut["reference"] == ref2
assert shut["entered_at"] and shut["exited_at"], shut
for field in PERSONAL:
    assert field not in shut, field
assert "Asha Rao" not in gone.get_data(as_text=True)
assert "token" not in shut
# The refusal that comes back with it must not smuggle the details through.
refused_body = client.post(f"/api/pass/{entry2}/entry", headers=KEY, json=PHOTO).get_json()
for field in PERSONAL:
    assert field not in refused_body["visit"], field
# The same rule over WhatsApp.
shut_reply = say(APPROVER, ref2)
assert "Closed" in shut_reply and ref2 in shut_reply
assert "Asha Rao" not in shut_reply and "9876543210" not in shut_reply
print("  a dead code gives times only, on the web page and on WhatsApp")

print("an open pass still shows everything the guard needs")
live = new_request()
say(APPROVER, f"YES {live['reference']}")
open_pass = client.get(f"/api/pass/{live['reference']}", headers=KEY).get_json()
for field in PERSONAL:
    if field != "address":
        assert open_pass[field], field
# The gate needs no address, so no gate answer holds it, not even a refusal.
assert "address" not in open_pass
assert "address" not in client.get(f"/api/pass/{entry_of(live)}", headers=KEY).get_json()
refused_entry = client.post(f"/api/pass/{exit_of(live)}/entry", headers=KEY).get_json()
assert "visit" in refused_entry and "address" not in refused_entry["visit"]
assert payload["address"] not in client.get("/api/gate/board", headers=KEY).get_data(as_text=True)
assert "code_kind" not in open_pass
assert "decided_phone" not in open_pass, "the approver's number is for the admin only"
# The token opens the visitor's page, which shows the gate code. A guard who
# taps a name on the board must never get from the reference to the code.
for gate_answer in (open_pass,
                    client.get(f"/api/pass/{entry_of(live)}", headers=KEY).get_json()):
    assert "token" not in gate_answer, "the gate must never get the visitor's private link"
assert client.post(f"/api/pass/{ref2}/sideways", headers=KEY).status_code == 404
assert client.post("/api/pass/VR-9999/entry", headers=KEY).status_code == 404
assert client.get(f"/api/pass/{ref2}", headers={"X-Gate-Key": "wrong"}).status_code == 403

print("the gate board")
assert client.get("/api/gate/board").status_code == 403
assert client.get("/api/gate/board", headers={"X-Gate-Key": "wrong"}).status_code == 403
board = client.get("/api/gate/board", headers=KEY).get_json()
expected_refs = [v["reference"] for v in board["expected"]]
inside_refs = [v["reference"] for v in board["inside"]]
assert live["reference"] in expected_refs, expected_refs          # approved, not used
assert ref2 not in expected_refs + inside_refs                     # closed
assert second_in["reference"] in inside_refs, inside_refs          # inside
waiting_one = new_request()
assert waiting_one["reference"] not in expected_refs + inside_refs  # pending
# The board carries what the list shows, and nothing it does not.
shown = board["expected"][0]
assert set(shown) == {"reference", "name", "visiting", "guests", "status",
                    "created_at", "decided_at", "entered_at", "expires_at"}, set(shown)
# The board is the one list every guard sees. It must hold no gate code.
board_text = client.get("/api/gate/board", headers=KEY).get_data(as_text=True)
assert not any(c in board_text for c in (entry_of(live), exit_of(live),
                                        entry_of(second_in), exit_of(second_in)))
# Inside is ordered longest first, so whoever never left is at the top.
entered = [v["entered_at"] for v in board["inside"]]
assert entered == sorted(entered), entered
# A pass approved long ago stays on the list while it is valid, and leaves it once it expires.
stale = new_request()
say(APPROVER, f"YES {stale['reference']}")
with db.connect() as conn:
    conn.execute("UPDATE visits SET decided_at = %s, created_at = %s WHERE reference = %s",
                 (db.ago(1.9), db.ago(1.9), stale["reference"]))
db.forget_cache()
board = client.get("/api/gate/board", headers=KEY).get_json()
assert stale["reference"] in [v["reference"] for v in board["expected"]], "valid for 48 hours"
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 (db.ago(2.1), stale["reference"]))
db.forget_cache()
board = client.get("/api/gate/board", headers=KEY).get_json()
assert stale["reference"] not in [v["reference"] for v in board["expected"]]
assert client.get(f"/api/pass/{stale['reference']}", headers=KEY).get_json()["status"] == "expired"
print(f"  {len(board['inside'])} inside, {len(board['expected'])} expected")

print("a declined pass never opens the gate")
bad = new_request()
say(APPROVER, f"NO {bad['reference']}")
refused = client.post(f"/api/pass/{entry_of(bad)}/entry", headers=KEY, json=PHOTO)
assert refused.status_code == 409 and "Declined" in refused.get_json()["error"]

print("several waiting requests")
a, b = new_request(), new_request()
many = say(APPROVER, "YES")
assert "These requests are waiting" in many
assert a["reference"] in many and b["reference"] in many and "Asha Rao" in many
say(APPROVER, f"YES {a['reference']}")
assert client.get(f"/api/visit/{a['token']}").get_json()["status"] == "approved"
# Only b waits now. A reference that does not read must not decide b.
for typo in ("VR-40222", "VR 99", "please"):
    reply = say(APPROVER, f"NO {typo}")
    assert "No request has reference" in reply, reply
    assert visits.get(b["reference"])["status"] == "pending", typo
# VR 4022 and VR4022 read as VR-4022. YES alone still means the one waiting.
for typed in ("YES VR 4022", "YES vr4022", "YES 4022"):
    assert whatsapp.read_reply(typed) == ("decide", db.APPROVED, "VR-4022"), typed
assert whatsapp.read_reply("YES") == ("decide", db.APPROVED, None)

print("escalation never decides, it only asks again")
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 (db.ago(1 / 24), b["reference"]))
db.forget_cache()
due = visits.due_for_escalation()
assert [v["reference"] for v in due] == [b["reference"]], due
whatsapp.notify_backup(due[0], people.approvers_for(people.approver_table(), due[0]["reason"]))
visits.mark_escalated(b["reference"])
after = client.get(f"/api/visit/{b['token']}").get_json()
assert after["status"] == "escalated" and after["escalated_at"]
assert "Backup approver" in sent[-1][1]
assert templates[-1][0] == "+911234567890" and templates[-1][1][1].startswith("Backup")
# An escalated request is still undecided, and a visitor inside never escalates.
assert b["reference"] in [v["reference"] for v in visits.open_requests()]
assert ref2 not in [v["reference"] for v in visits.open_requests()]
assert ref2 not in [v["reference"] for v in visits.due_for_escalation()]

print("retention deletes records older than RETAIN_DAYS")
old = new_request()
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", old["reference"]))
db.forget_cache()
old_entry = entry_of(old)
assert visits.purge_old() >= 1
assert visits.get(old["reference"]) is None
# Its codes go with it, so a purged pass can never be looked up again.
assert visits.codes_of(old["reference"]) == {}
assert visits.by_code(old_entry) == (None, None)
assert client.get(f"/api/visit/{old['token']}").status_code == 404
# Today's records survive the purge.
assert visits.get(a["reference"]) is not None
# A photo goes with its visit, and the photos of kept visits stay.
gone, kept = new_request(), new_request()
with db.connect() as conn:
    for photographed in (gone, kept):
        conn.execute("INSERT INTO photos (reference, media_id, taken_at) VALUES (%s, %s, %s)",
                     (photographed["reference"], "media.x", db.now()))
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", gone["reference"]))
db.forget_cache()
visits.purge_old()
assert entries.photo_of(gone["reference"]) is None
assert entries.photo_of(kept["reference"]) is not None
# No code outlives its visit, including those of requests deleted after a
# failed send.
with db.connect() as conn:
    orphans = conn.execute("SELECT COUNT(*) AS n FROM gate_codes WHERE reference NOT IN"
                           " (SELECT reference FROM visits)").fetchone()["n"]
assert orphans == 0, orphans
print("  old visits, their photos and their codes deleted, today's kept")

print("each reason has its own two approvers")

DELIVERY_MAIN, DELIVERY_BACKUP = "+919000000001", "+919000000002"
real_approvers = config.APPROVERS
config.APPROVERS = {**real_approvers, "Delivery": (DELIVERY_MAIN, DELIVERY_BACKUP)}
try:
    delivery = client.post("/api/requests", json={**payload, "reason": "Delivery"}).get_json()
    assert templates[-1][0] == DELIVERY_MAIN, templates[-1]
    student = new_request()
    assert templates[-1][0] == "+911234567890", templates[-1]
    # A reason the visitor typed in goes to the approvers for the reason Other.
    client.post("/api/requests", json={**payload, "reason": "Fix the lift"})
    assert templates[-1][0] == config.APPROVERS["Other"][0], templates[-1]

    # Nobody decides a request of a reason they do not approve.
    refused_reply = say(APPROVER, f"YES {delivery['reference']}")
    assert "another approver" in refused_reply, refused_reply
    assert visits.get(delivery["reference"])["status"] == "pending"
    wrong = say(DELIVERY_MAIN[1:], f"YES {student['reference']}")
    assert "another approver" in wrong, wrong
    # Each approver's waiting list holds only their own reasons.
    table = people.approver_table()
    waiting_delivery = [v["reference"] for v in access.waiting_for(DELIVERY_MAIN, table)]
    assert waiting_delivery == [delivery["reference"]], waiting_delivery
    assert delivery["reference"] not in [
        v["reference"] for v in access.waiting_for(APPROVER, table)]
    # The backup for the reason can decide it, before or after escalation.
    assert "is now approved" in say(DELIVERY_BACKUP[1:], f"YES {delivery['reference']}")
    assert visits.get(delivery["reference"])["status"] == "approved"
    assert visits.get(delivery["reference"])["decided_by"] == db.BY_BACKUP
    assert visits.get(delivery["reference"])["decided_phone"] == DELIVERY_BACKUP

    # Escalation goes to the backup of the request's own reason.
    late = client.post("/api/requests", json={**payload, "reason": "Delivery"}).get_json()
    with db.connect() as conn:
        conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                     (db.ago(1 / 24), late["reference"]))
    db.forget_cache()
    timer.escalate_due()
    assert templates[-1][0] == DELIVERY_BACKUP, templates[-1]
    assert templates[-1][1][0] == late["reference"]
finally:
    config.APPROVERS = real_approvers
print("  routing, deciding, waiting lists and escalation all follow the reason")

print("the admin list")
# A guard holds the gate key. It must never open the admin list.
for path in ("/api/admin/visits", "/api/admin/summary", "/api/admin/export.csv"):
    assert client.get(path).status_code == 403, path
    assert client.get(path, headers={"X-Admin-Key": "guess"}).status_code == 403, path
    assert client.get(path, headers={"X-Admin-Key": GATE_KEY_TEXT}).status_code == 403, path
assert client.get("/admin").status_code == 200
# With no ADMIN_KEY, or the gate key as ADMIN_KEY, the admin page is locked.
# Either one would otherwise let the guards in. The rest of the app runs.
for bad_key in ("", "test-gate-key-long-enough", " test-gate-key-long-enough "):
    os.environ["ADMIN_KEY"] = bad_key
    locked_key, why = config.read_admin_key()
    assert locked_key == "" and "ADMIN_KEY" in why, (bad_key, why)
os.environ["ADMIN_KEY"] = "test-admin-key-long-enough"
assert config.read_admin_key() == ("test-admin-key-long-enough", "")
# A short key, or the example from .env.example, locks the admin page too.
for weak_key in ("short-admin-key", "change-me-to-something-else-random"):
    os.environ["ADMIN_KEY"] = weak_key
    locked_key, why = config.read_admin_key()
    assert locked_key == "" and "ADMIN_KEY" in why and config.MAKE_KEY in why, (weak_key, why)
os.environ["ADMIN_KEY"] = "test-admin-key-long-enough"


def starts_with(**settings):
    """(started, error text) with these settings changed, in a new process."""
    env = {**os.environ, **settings}
    run = subprocess.run([sys.executable, "-c", "import config"], env=env,
                         capture_output=True, text=True, cwd=os.path.dirname(__file__) or ".")
    return run.returncode == 0, run.stderr


# Unsafe settings stop the start, with a sentence that says what to set.
assert starts_with()[0], "the test settings start"
for changes, says in (({"ALLOW_UNSIGNED_WEBHOOK": ""}, "META_APP_SECRET"),
                      ({"GATE_KEY": "short"}, "20 characters"),
                      ({"GATE_KEY": "change-me-to-something-random"}, ".env.example")):
    started, error = starts_with(**changes)
    assert not started and says in error, (changes, error[-300:])
assert starts_with(ALLOW_UNSIGNED_WEBHOOK="", META_APP_SECRET="a-real-secret")[0]
# A key with a letter outside ASCII is a wrong key, not a server error.
assert client.get("/api/gate/board", headers={"X-Gate-Key": "clé"}).status_code == 403
assert client.get("/api/admin/summary", headers={"X-Admin-Key": "clé"}).status_code == 403
# Locked, every admin call is refused, even an empty key that would match an
# empty ADMIN_KEY, and even the right key from before.
real_admin = config.ADMIN_KEY, config.ADMIN_LOCKED
os.environ["ADMIN_KEY"] = ""
config.ADMIN_KEY, config.ADMIN_LOCKED = config.read_admin_key()
try:
    for path in ("/api/admin/visits", "/api/admin/summary", "/api/admin/export.csv"):
        for headers in ({}, {"X-Admin-Key": ""}, {"X-Admin-Key": GATE_KEY_TEXT}, ADMIN):
            locked = client.get(path, headers=headers)
            assert locked.status_code == 503, (path, headers, locked.status_code)
            assert "ADMIN_KEY" in locked.get_json()["error"], path
    # The gate and the visitor form do not depend on the admin key.
    assert client.get("/api/gate/board", headers=KEY).status_code == 200
finally:
    os.environ["ADMIN_KEY"] = "test-admin-key-long-enough"
    config.ADMIN_KEY, config.ADMIN_LOCKED = real_admin

# More than one page of visits. The rate limit would refuse some of them.
for number in range(60):
    limits.forget_hits()
    page_request = client.post("/api/requests", json={**payload, "name": f"Page Test {number}"})
    assert page_request.status_code == 201, page_request.get_data(as_text=True)
limits.forget_hits()
total = sum(visits.status_counts().values())
seen, cursor, page_count = [], None, 0
while True:
    query = f"/api/admin/visits?after={cursor}" if cursor else "/api/admin/visits"
    page = client.get(query, headers=ADMIN).get_json()
    page_count += 1
    for row in page["visits"]:
        # The token is the visitor's private status link. It never leaves.
        assert "token" not in row, row
        table = people.approver_table()
        assert row["approvers"] == list(people.approvers_for(table, row["reason"]))
    seen += [row["reference"] for row in page["visits"]]
    cursor = page["next"]
    if not cursor:
        break
    cursor = cursor.replace("+", "%2B")
assert len(seen) == len(set(seen)) == total, (len(seen), len(set(seen)), total)
assert page_count == -(-total // admin_routes.ADMIN_PAGE), page_count
times = [visits.get(r)["created_at"] for r in seen]
assert times == sorted(times, reverse=True)

waiting = client.get("/api/admin/visits?status=waiting", headers=ADMIN).get_json()["visits"]
assert waiting and {v["status"] for v in waiting} <= {"pending", "escalated"}
found = client.get("/api/admin/visits?q=page%20test%2042", headers=ADMIN).get_json()
assert [v["name"] for v in found["visits"]] == ["Page Test 42"], found
# % and _ in a search are letters, not wildcards.
assert client.get("/api/admin/visits?q=%25", headers=ADMIN).get_json()["visits"] == []
assert client.get("/api/admin/visits?status=nope", headers=ADMIN).status_code == 400
assert client.get("/api/admin/visits?after=x", headers=ADMIN).status_code == 400

summary = client.get("/api/admin/summary", headers=ADMIN).get_json()
assert sum(summary["counts"].values()) == total
assert [a["reason"] for a in summary["approvers"]] == list(config.REASONS)
assert client.get("/api/admin/export.csv", headers=ADMIN).status_code == 200
# No list, summary or export holds a gate code. Only the visitor's pass does.
live_codes = (entry_of(live), exit_of(live))
for path, headers in (("/api/admin/visits", ADMIN),
                      (f"/api/admin/visits?q={live['reference']}", ADMIN),
                      ("/api/admin/summary", ADMIN), ("/api/admin/export.csv", ADMIN)):
    answer = client.get(path, headers=headers).get_data(as_text=True)
    assert not any(c in answer for c in live_codes), path
decided = client.get(f"/api/admin/visits?q={live['reference']}", headers=ADMIN).get_json()
assert decided["visits"][0]["decided_phone"] == "+" + APPROVER, decided
print(f"  {total} visits over {page_count} pages, none twice, none missed, no token, no code")

print("pages are served")
for path in ("/", "/app.js", "/gate", "/gate.js", "/admin", "/admin.js", "/shared.js", "/sw.js"):
    assert client.get(path).status_code == 200, path

print("every answer carries the security headers")
page_answer = client.get("/admin")
not_changed = client.get("/admin", headers={"If-None-Match": page_answer.headers["ETag"]})
assert not_changed.status_code == 304
script_tag = re.search(r'src="(admin\.js\?v=\w+)"', page_answer.get_data(as_text=True))
assert script_tag, "the admin page loads its script by version"
script_path = script_tag[1]
for answer in (page_answer, not_changed, client.get("/" + script_path),
               client.get("/api/config"), client.get("/api/visit/nope"),
               client.get("/api/admin/visits")):
    for name, value in pages.SECURITY_HEADERS.items():
        assert answer.headers.get(name) == value, (answer.status_code, name)
policy = pages.CONTENT_POLICY
assert "frame-ancestors 'self'" in policy and "object-src 'none'" in policy
assert "img-src 'self' data:" in policy, "the logo is a data: image"
print("  page, 304, script, API, 404 and 403 all carry them")

print("the health check names what failed and never why")
meta_calls = []
real_token_works = whatsapp.token_works
whatsapp.token_works = lambda: meta_calls.append(1) or True
application.forget_meta_check()
healthy = client.get("/api/health")
assert healthy.status_code == 200 and healthy.get_json() == {"database": True, "whatsapp": True}
assert client.get("/api/health").status_code == 200
assert len(meta_calls) == 1, "Meta is asked at most once an hour"
whatsapp.token_works = lambda: meta_calls.append(1) or False
application.forget_meta_check()
expired_token = client.get("/api/health")
assert expired_token.status_code == 503
assert expired_token.get_json() == {"database": True, "whatsapp": False}, "no reason, no token"
client.get("/api/health")
assert len(meta_calls) == 2, "a failure is asked again after 5 minutes, not at once"
application.forget_meta_check()
real_ping = db.ping
db.ping = lambda: False
whatsapp.token_works = lambda: True
assert client.get("/api/health").get_json() == {"database": False, "whatsapp": True}
db.ping = real_ping
whatsapp.token_works = real_token_works
assert db.ping() is True
# The real check, with Meta's answers stubbed: an expired token and a lost connection.
real_get = whatsapp.requests.get
whatsapp.requests.get = lambda *_a, **_k: type("R", (), {"ok": False, "status_code": 401})()
assert whatsapp.token_works() is False


def no_network(*_args, **_kwargs):
    raise whatsapp.requests.ConnectionError("down")


whatsapp.requests.get = no_network
assert whatsapp.token_works() is False
whatsapp.requests.get = lambda *_a, **_k: type("R", (), {"ok": True, "status_code": 200})()
assert whatsapp.token_works() is True
whatsapp.requests.get = real_get
limits.forget_hits()
print("  200 when both work, 503 with the failed part, Meta asked once an hour")

print("the timer sleeps until the next deadline")
real_next_due = visits.next_due
moment = datetime.now(timezone.utc)
for due, low, high in ((None, 3600, 3600),
                       (moment + timedelta(minutes=10), 590, 602),
                       (moment - timedelta(minutes=5), 30, 30),
                       (moment + timedelta(hours=5), 3600, 3600)):
    visits.next_due = lambda when=due: when
    wait = timer.seconds_to_next_round()
    assert low <= wait <= high, (due, wait)
visits.next_due = real_next_due
timer.wake.clear()
soon = new_request()
assert timer.wake.is_set(), "a new request wakes the timer"
due = visits.next_due()
made = datetime.fromisoformat(soon["created_at"])
assert due is not None and due <= made + timedelta(minutes=config.ESCALATE_MINUTES), due
print("  idle an hour, a deadline on time, overdue in 30 seconds, a new request wakes it")
cfg = client.get("/api/config").get_json()
assert cfg["escalate_minutes"] == 30 and cfg["retain_days"] == 1
assert "gate_key" not in str(cfg).lower(), "the gate key must never be published"

print("export of every entry and exit")
# The whole history is for the admin only. The gate has no export at all.
assert client.get("/api/export.csv", headers=KEY).status_code == 404
assert client.get("/api/admin/export.csv", headers=KEY).status_code == 403
assert client.get("/api/admin/export.csv").status_code == 403

dump = client.get("/api/admin/export.csv", headers=ADMIN)
assert dump.status_code == 200
assert "text/csv" in dump.headers["Content-Type"]
assert "attachment" in dump.headers["Content-Disposition"]

import csv as _csv
import io as _io
rows = list(_csv.DictReader(_io.StringIO(dump.get_data(as_text=True))))
head = rows[0].keys()
for column in ("reference", "name", "status", "entered_at", "exited_at"):
    assert column in head, column

# The visitor who went in and out must carry both times.
done = [r for r in rows if r["reference"] == ref2]
assert len(done) == 1, done
assert done[0]["status"] == "closed"
assert done[0]["entered_at"] and done[0]["exited_at"], done[0]
# Guests come out readable, not as JSON.
assert done[0]["guests"] == "Ravi Rao", done[0]["guests"]
# The log says when the gate photo was taken, on the web gate as on WhatsApp.
assert done[0]["photo_at"] == done[0]["entered_at"], done[0]
photographed = next(r for r in rows if r["reference"] == code)
assert photographed["photo_at"] == photographed["entered_at"], photographed
# A visit that never entered has empty times rather than the word None.
never = next(r for r in rows if r["status"] == "declined")
assert never["entered_at"] == "" and never["exited_at"] == ""

# A spreadsheet must not run the visitor's text. Excel and Sheets treat a cell
# opening with = + - @ as a formula, so the export quotes those cells first.
attack = dict(payload, name="=HYPERLINK(\"http://evil.test\",\"click\")",
              address="+1+1", reason="@SUM(1:9)", visiting="-2+3")
assert client.post("/api/requests", json=attack).status_code == 201
armed = client.get("/api/admin/export.csv", headers=ADMIN).get_data(as_text=True)
row = next(r for r in _csv.DictReader(_io.StringIO(armed))
           if r["name"].endswith('click")'))
for column in ("name", "address", "reason", "visiting"):
    assert row[column].startswith("'"), (column, row[column])
# The text itself is kept, only disarmed.
assert row["name"] == "'=HYPERLINK(\"http://evil.test\",\"click\")"
# Ordinary values are left exactly as they were.
assert not row["reference"].startswith("'")
print("  formula cells disarmed in the export")
print(f"  {len(rows)} visits exported with entry and exit times")

print("rate limits on the public address")
limits.forget_hits()

# Creating requests is capped so a stranger cannot spam the approver's phone.
codes_before = len(visits.all_visits())
limit = __import__("config").REQUESTS_PER_HOUR
statuses = [client.post("/api/requests", json=payload).status_code for _ in range(limit + 5)]
assert statuses.count(201) == limit, statuses
assert statuses.count(429) == 5, statuses
print(f"  request flood: {statuses.count(201)} allowed, {statuses.count(429)} refused")

# Wrong gate keys are always refused.
limits.forget_hits()
tries = [client.get("/api/pass/VR-0001", headers={"X-Gate-Key": f"guess{i}"}).status_code
         for i in range(65)]
assert all(s == 403 for s in tries), set(tries)
print(f"  gate key: {len(tries)} wrong guesses all refused")

# The correct key must keep working no matter how many wrong ones came before.
# Everyone at one gate shares an address, so a lockout would shut out the guard.
for _ in range(50):
    assert client.get(f"/api/pass/{ref2}", headers=KEY).status_code == 200
print("  correct key still works after 65 wrong guesses, and 50 times running")

# The request limit must not be buyable with a made-up address header.
limits.forget_hits()
for i in range(20):
    client.post("/api/requests", json={**payload, "phone": "123"},
                headers={"X-Forwarded-For": f"9.9.9.{i}"})
buckets = limits.hit_buckets()
assert buckets == 1, f"spoofed headers created {buckets} buckets"
print("  20 calls behind 20 fake addresses still counted as one caller")

# The limit must never block Meta's webhook, which shares no bucket with the gate.
limits.forget_hits()
fresh = new_request()
for _ in range(70):
    client.get("/api/pass/VR-0001", headers={"X-Gate-Key": "guess"})
ok = client.post("/webhook/whatsapp", json=inbound(APPROVER, f"YES {fresh['reference']}"))
assert ok.status_code == 200
assert client.get(f"/api/visit/{fresh['token']}").get_json()["status"] == "approved"
print("  webhook still works while the gate is rate limited")

# A visitor polling their own status is never rate limited.
limits.forget_hits()
polls = [client.get(f"/api/visit/{fresh['token']}").status_code for _ in range(50)]
assert set(polls) == {200}, set(polls)
print("  50 visitor polls all served")

# The table of callers stays bounded. Callers silent for an hour are dropped
# once it passes MAX_CALLERS, and callers heard from recently are kept.
limits.forget_hits()
limits.add_silent_callers(limits.MAX_CALLERS + 1, 7200)
assert client.post("/api/requests", json={**payload, "phone": "123"}).status_code == 400
assert limits.hit_buckets() == 1, limits.hit_buckets()
print(f"  {limits.MAX_CALLERS + 1} silent callers swept out, the live one kept")
limits.forget_hits()

print("migrations run once, so a restart keeps every visit")
kept_visit = new_request()
assert db.init() == len(migrations.MIGRATIONS)
assert db.init() == len(migrations.MIGRATIONS)
with db.connect() as conn:
    versions = [row["version"] for row in
                conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
assert versions == list(range(1, len(migrations.MIGRATIONS) + 1)), versions
assert visits.get(kept_visit["reference"]) is not None
# A step added later runs on the next start, and the visits stay.
migrations.MIGRATIONS.append("ALTER TABLE visits ADD COLUMN test_note TEXT")
try:
    assert db.init() == len(migrations.MIGRATIONS)
    assert visits.get(kept_visit["reference"])["test_note"] is None
finally:
    migrations.MIGRATIONS.pop()
print(f"  schema at version {len(migrations.MIGRATIONS)}, a new column added, visits kept")

print("scripts are cached by version, pages are checked")
for path, script in (("/", "app.js"), ("/gate", "gate.js"), ("/admin", "admin.js")):
    shown = client.get(path)
    assert shown.headers["Cache-Control"] == "no-cache", shown.headers
    address = f"{script}?v={pages.SCRIPT_VERSIONS[script]}"
    assert address in shown.get_data(as_text=True), path
    kept = client.get("/" + address)
    assert kept.status_code == 200
    assert "immutable" in kept.headers["Cache-Control"], kept.headers
    # A wrong or missing version is never kept, so no address can hold stale code.
    for other in (f"/{script}", f"/{script}?v=old"):
        assert "immutable" not in client.get(other).headers.get("Cache-Control", ""), other
    again = client.get(path, headers={"If-None-Match": shown.headers["ETag"]})
    assert again.status_code == 304 and not again.data, path
# The service worker is checked on every load, or a phone could keep an old one.
worker = client.get("/sw.js")
assert worker.status_code == 200 and "immutable" not in worker.headers.get("Cache-Control", "")
print("  3 pages: 304 when unchanged, each script kept for a year under its hash")

print("each request makes as few database trips as it can")
real_connect, trips = db.connect, []
db.connect = lambda: trips.append(1) or real_connect()
try:
    counted = new_request()
    say(APPROVER, f"YES {counted['reference']}")
    counted_code = entry_of(counted)
    for label, call, most in (
        ("status check", lambda: client.get(f"/api/visit/{counted['token']}"), 1),
        ("pass lookup", lambda: client.get(f"/api/pass/{counted_code}", headers=KEY), 1),
        ("entry", lambda: client.post(f"/api/pass/{counted_code}/entry",
                                      headers=KEY, json=PHOTO), 2),
    ):
        trips.clear()
        assert call().status_code == 200, label
        assert len(trips) <= most, (label, len(trips))

    # Open pages repeat their reads. With no write between, they cost no trip,
    # so Neon can sleep while a gate page or a visitor's page stays open.
    ravi_key = people.add_guard("Cache Guard", "+919800000777")
    status = lambda: client.get(f"/api/visit/{counted['token']}")  # noqa: E731
    gate_board = lambda: client.get("/api/gate/board", headers={"X-Gate-Key": ravi_key})  # noqa: E731
    for label, call in (("status check", status), ("board with a guard's key", gate_board)):
        call()
        trips.clear()
        assert call().status_code == 200 and len(trips) == 0, (label, len(trips))
    # A write makes them stale, so the next read goes to the database once.
    exit_code = exit_of(counted)
    client.post(f"/api/pass/{exit_code}/exit", headers=KEY)
    trips.clear()
    assert status().get_json()["status"] == "closed", "a write is seen at once"
    assert len(trips) == 1, len(trips)
    trips.clear()
    # Every write clears the whole cache, so the guard list is read again too.
    assert gate_board().status_code == 200 and len(trips) == 2, len(trips)
    people.remove_guard("+919800000777")
    # An unknown token is never kept, so a scanner cannot fill the memory.
    for _ in range(2):
        trips.clear()
        assert client.get("/api/visit/not-a-token").status_code == 404
        assert len(trips) == 1, len(trips)
    # In the first minutes after start, the old version may still write, so nothing is kept.
    db.CACHE_AFTER_SECONDS = 10**9
    try:
        status()
        trips.clear()
        status()
        assert len(trips) == 1, "nothing is kept while the server is new"
    finally:
        db.CACHE_AFTER_SECONDS = 0
finally:
    db.connect = real_connect
print("  status check 1, pass lookup 1, entry 2; a repeated poll 0 until the next write")

print("every write to a cached table clears the cache")
# The cache is right only while each change to these tables goes through @writes.
# A new database function that forgets it fails here, not as stale pages later.
CACHED_TABLES = re.compile(
    r"\b(INSERT INTO|UPDATE|DELETE FROM)\s+(visits|guards|photos|gate_codes)\b")
forgot = []
for module in ("db.py", "visits.py", "entries.py", "people.py"):
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), module),
              encoding="utf-8") as db_file:
        db_source = db_file.read()
    for node in ast.parse(db_source).body:
        if isinstance(node, ast.FunctionDef) and node.name != "migrate":
            # @writes in db.py, @db.writes in the other three.
            names = [getattr(d, "id", "") or getattr(d, "attr", "") for d in node.decorator_list]
            body = ast.get_source_segment(db_source, node) or ""
            if CACHED_TABLES.search(body) and "writes" not in names:
                forgot.append(f"{module}: {node.name}")
assert not forgot, f"these change cached tables without @writes: {forgot}"
print("  every function that changes visits, guards, photos or codes has @writes")

print("a dropped connection is retried for reads, never for writes")
tries = []


@db.read
def flaky_read():
    tries.append(1)
    if len(tries) == 1:
        raise psycopg.OperationalError("server closed the connection")
    return "read"


assert flaky_read() == "read" and len(tries) == 2


@db.read
def full_pool():
    tries.append(1)
    raise PoolTimeout("no connection")


tries.clear()
with contextlib.suppress(PoolTimeout):
    full_pool()
assert len(tries) == 1, "a full pool must not be waited on twice"

# The server ends every connection in the pool. The next read still works.
kept_visit = new_request()
with psycopg.connect(config.DATABASE_URL, autocommit=True) as killer:
    killer.execute("""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                      WHERE pid <> pg_backend_pid() AND datname = current_database()""")
assert visits.get(kept_visit["reference"])["reference"] == kept_visit["reference"]

# At start, a database that is still waking is tried again before giving up.
real_migrate, real_waits = db.migrate, db.START_WAITS
db.START_WAITS = (0, 0, 0, 0)
fails = []


def waking():
    if len(fails) < 3:
        fails.append(1)
        raise psycopg.OperationalError("the database system is starting up")
    return real_migrate()


def never_up():
    raise psycopg.OperationalError("the database is down")


db.migrate = waking
try:
    assert db.init() == len(migrations.MIGRATIONS) and len(fails) == 3
    db.migrate = never_up
    try:
        db.init()
        raise AssertionError("a database that never answers must stop the start")
    except psycopg.OperationalError:
        pass
finally:
    db.migrate, db.START_WAITS = real_migrate, real_waits
print("  retried after a drop, a full pool fails at once, the start waits for the database")

print("the admin page changes a reason's two approvers")
NEW_MAIN, NEW_BACKUP = "+919000000011", "+919000000012"


def set_pair(main_number, backup_number, reason="Event", key=None):
    return client.post("/api/admin/approvers", headers=key or ADMIN,
                       json={"reason": reason, "main": main_number, "backup": backup_number})


assert set_pair(NEW_MAIN, NEW_BACKUP, key=KEY).status_code == 403
assert set_pair(NEW_MAIN, NEW_BACKUP, reason="Party").status_code == 400
for bad_main, bad_backup, field in (("", NEW_BACKUP, "main"), (NEW_MAIN, "", "backup"),
                                    ("98765", NEW_BACKUP, "main"),
                                    (NEW_MAIN, "+91 90000 00011", "backup")):
    refused = set_pair(bad_main, bad_backup)
    assert refused.status_code == 400 and field in refused.get_json()["fields"], field
saved = set_pair("+91 90000-00011", NEW_BACKUP)
assert saved.status_code == 200, saved.get_json()
event_row = {"reason": "Event", "main": NEW_MAIN, "backup": NEW_BACKUP}
assert event_row in saved.get_json()["approvers"]
assert event_row in client.get("/api/admin/summary", headers=ADMIN).get_json()["approvers"]
event = client.post("/api/requests", json={**payload, "reason": "Event"}).get_json()
assert templates[-1][0] == NEW_MAIN, templates[-1]
# The old number loses the reason at once, and the new one can decide it.
assert "another approver" in say(APPROVER, f"YES {event['reference']}")
# An approver who is not the guard can look a request up.
assert event["reference"] in say(NEW_MAIN[1:], event["reference"])
assert "is now approved" in say(NEW_MAIN[1:], f"YES {event['reference']}")
assert visits.get(event["reference"])["decided_by"] == db.BY_MAIN
assert visits.get(event["reference"])["decided_phone"] == NEW_MAIN
with db.connect() as conn:
    conn.execute("DELETE FROM approvers")
db.forget_cache()
print("  both numbers required and checked, new number used at once, old one refused")

print("a request made in working hours is approved by itself")


def ist(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=config.WORK_TIMEZONE)


# Monday 5, Saturday 10 and Sunday 11 October 2026.
assert timer.auto_approve_time(ist(5, 9, 59)) is None
assert timer.auto_approve_time(ist(5, 10)) == "2026-10-05T05:00:00+00:00"
assert timer.auto_approve_time(ist(5, 16, 59)) == "2026-10-05T11:59:00+00:00"
assert timer.auto_approve_time(ist(5, 17)) is None
assert timer.auto_approve_time(ist(10, 12)) is not None
assert timer.auto_approve_time(ist(11, 12)) is None
# 04:30 UTC is 10:00 in India, so it counts.
assert timer.auto_approve_time(datetime(2026, 10, 5, 4, 30, tzinfo=timezone.utc)) \
    == "2026-10-05T05:00:00+00:00"

due, with_backup, declined, not_yet = (new_request() for _ in range(4))
with db.connect() as conn:
    for case, moment in ((due, "2020-01-01T00:00:00+00:00"),
                         (with_backup, "2020-01-01T00:00:00+00:00"),
                         (declined, "2020-01-01T00:00:00+00:00"),
                         (not_yet, "2999-01-01T00:00:00+00:00")):
        conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                     (moment, case["reference"]))
db.forget_cache()
visits.mark_escalated(with_backup["reference"])
say(APPROVER, f"NO {declined['reference']}")
before = len(sent)
timer.auto_approve_due()
for case in (due, with_backup):
    got = visits.get(case["reference"])
    assert got["status"] == "approved" and got["decided_by"] == db.BY_AUTO, got
    assert got["decided_phone"] is None, got
assert visits.get(declined["reference"])["status"] == "declined"
assert visits.get(not_yet["reference"])["status"] == "pending"
notices = [body for _, body in sent[before:] if "approved automatically" in body]
assert len(notices) == 2, notices
timer.auto_approve_due()
assert len(sent) == before + 2, "a second round must not approve or notify again"
view = client.get(f"/api/visit/{due['token']}").get_json()
assert view["status"] == "approved" and view["entry_code"]
private = {"decided_by", "decided_phone", "auto_approve_at"}
assert not private & view.keys(), "the visitor must not see it"
# The answer to a new request is the visitor's too, also in working hours.
real_auto_time = timer.auto_approve_time
timer.auto_approve_time = lambda _moment: "2999-01-01T00:00:00+00:00"
in_hours = client.post("/api/requests", json=payload)
timer.auto_approve_time = real_auto_time
assert in_hours.status_code == 201
assert visits.get(in_hours.get_json()["reference"])["auto_approve_at"], "the server keeps the time"
assert not private & in_hours.get_json().keys(), "the new request must not tell the visitor"
print("  10:00 to 16:59 Monday to Saturday only, a NO first wins, approvers told once")

print("a pass works for PASS_HOURS after the request, then never again")
assert config.PASS_HOURS == 48
assert client.get("/api/config").get_json()["pass_hours"] == 48


def made_hours_ago(ticket, hours):
    with db.connect() as db_conn:
        db_conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                        (db.ago(hours / 24), ticket["reference"]))
    db.forget_cache()


# 47 hours old: approval and entry still work, and the pass names its end.
young = new_request()
made_hours_ago(young, 47)
assert "is now approved" in say(APPROVER, f"YES {young['reference']}")
view = client.get(f"/api/visit/{young['token']}").get_json()
assert view["status"] == "approved" and view["entry_code"] and view["expires_at"], view
assert client.post(f"/api/pass/{entry_of(young)}/entry", headers=KEY, json=PHOTO).status_code == 200

# 49 hours old and approved: nothing lets this visitor in.
late_pass = new_request()
say(APPROVER, f"YES {late_pass['reference']}")
made_hours_ago(late_pass, 49)
view = client.get(f"/api/visit/{late_pass['token']}").get_json()
assert view["status"] == "expired" and "entry_code" not in view, view
gate_try = client.post(f"/api/pass/{entry_of(late_pass)}/entry", headers=KEY, json=PHOTO)
refusal = gate_try.get_json()
assert gate_try.status_code == 409 and "expired" in refusal["error"], refusal
assert client.get(f"/api/pass/{entry_of(late_pass)}", headers=KEY).get_json()["status"] == "expired"
assert "expired" in say(APPROVER, f"IN {entry_of(late_pass)}").lower()
assert entries.check_in(late_pass["reference"], "test", JPEG) is None, "the UPDATE checks the time"
assert "Expired" in say(APPROVER, late_pass["reference"])

# The race: IN is accepted, then the pass expires before the photo arrives.
racing = new_request()
say(APPROVER, f"YES {racing['reference']}")
assert "Take a photo" in say(APPROVER, f"IN {entry_of(racing)}")
made_hours_ago(racing, 49)
assert "expired" in snap(APPROVER).lower()
assert visits.get(racing["reference"])["status"] == "expired"

# 49 hours old and never answered: it cannot be approved, escalated or picked by YES alone.
unanswered = new_request()
made_hours_ago(unanswered, 49)
reply = say(APPROVER, f"YES {unanswered['reference']}")
assert "expired" in reply and "new request" in reply, reply
table = people.approver_table()
waiting_refs = [v["reference"] for v in access.waiting_for(APPROVER, table)]
assert unanswered["reference"] not in waiting_refs
before = len(templates)
timer.escalate_due()
assert unanswered["reference"] not in [t[1][0] for t in templates[before:]], "no backup for it"
assert visits.decide(unanswered["reference"], db.APPROVED, db.BY_AUTO) is None

# A visitor already inside can always leave, however old the request.
staying = new_request()
say(APPROVER, f"YES {staying['reference']}")
client.post(f"/api/pass/{entry_of(staying)}/entry", headers=KEY, json=PHOTO)
made_hours_ago(staying, 72)
assert client.get(f"/api/visit/{staying['token']}").get_json()["status"] == "inside"
assert client.post(f"/api/pass/{exit_of(staying)}/exit", headers=KEY).status_code == 200

# The background round saves the status, so the admin counts and filter match.
assert visits.expire_old() >= 2
assert visits.expire_old() == 0, "a second round changes nothing"
for gone_pass in (late_pass, unanswered):
    with db.connect() as conn:
        stored = conn.execute("SELECT status FROM visits WHERE reference = %s",
                              (gone_pass["reference"],)).fetchone()["status"]
    assert stored == "expired", stored
expired_rows = client.get("/api/admin/visits?status=expired", headers=ADMIN).get_json()["visits"]
assert {late_pass["reference"], unanswered["reference"]} <= {v["reference"] for v in expired_rows}
assert client.get("/api/admin/summary", headers=ADMIN).get_json()["counts"]["expired"] >= 2
# A late reply to a pass already saved as expired gets the same answer.
assert "expired" in say(APPROVER, f"NO {late_pass['reference']}")
print("  47 hours works, 49 hours refused everywhere, exit always works, status saved")

print("a forgotten key goes to its own number, never to the page")
limits.forget_hits()
sent.clear()
gate_reply = client.post("/api/forgot-key/gate")
assert gate_reply.get_json() == {"sent_to": whatsapp.digits(config.GUARD)[-4:]}
assert sent[-1][0] == config.GUARD and "test-gate-key-long-enough" in sent[-1][1]
assert "test-gate-key-long-enough" not in gate_reply.get_data(as_text=True)
admin_reply = client.post("/api/forgot-key/admin")
assert admin_reply.status_code == 200
assert sent[-1][0] == config.ADMIN_PHONE and "test-admin-key-long-enough" in sent[-1][1]
assert "test-admin-key-long-enough" not in admin_reply.get_data(as_text=True)
assert client.post("/api/forgot-key/wifi").status_code == 404
client.post("/api/forgot-key/gate")
client.post("/api/forgot-key/gate")
assert client.post("/api/forgot-key/gate").status_code == 429
# Ten tries an hour in all, even from many addresses.
limits.forget_hits()
config.BEHIND_PROXY = True
try:
    codes = [client.post("/api/forgot-key/admin",
                         headers={"X-Forwarded-For": f"10.0.0.{n}"}).status_code
             for n in range(11)]
finally:
    config.BEHIND_PROXY = False
    limits.forget_hits()
assert codes == [200] * 10 + [429], codes
# KEY on WhatsApp answers only the numbers that hold a key.
gate_only = say(APPROVER, "KEY")
assert "test-gate-key-long-enough" in gate_only and "test-admin-key-long-enough" not in gate_only
assert "test-admin-key-long-enough" in say(config.ADMIN_PHONE[1:], "KEY")
# A guard never gets the admin key, even when ADMIN_PHONE is the gate desk.
real_admin_phone = config.ADMIN_PHONE
config.ADMIN_PHONE = config.GUARD
try:
    limits.forget_hits()
    assert client.post("/api/forgot-key/admin").status_code == 503
    assert "test-admin-key-long-enough" not in say(APPROVER, "KEY")
finally:
    config.ADMIN_PHONE = real_admin_phone
    limits.forget_hits()
sent_before = len(sent)
client.post("/webhook/whatsapp", json=inbound(STRANGER, "KEY"))
assert len(sent) == sent_before, "a stranger must get no reply"
print("  sent to the fixed number, 3 tries per caller and 10 in all each hour, KEY works")

print("the gate page lets nobody in without a photo")
limits.forget_hits()
shot = approved()
shot_entry = f"/api/pass/{entry_of(shot)}/entry"
no_photo = client.post(shot_entry, headers=KEY)
assert no_photo.status_code == 400 and no_photo.get_json()["error"] == checks.NO_PHOTO
assert status_of(shot) == "approved" and entries.photo_of(shot["reference"]) is None
png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
not_jpeg = "data:image/jpeg;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n").decode()
too_big = "data:image/jpeg;base64," + base64.b64encode(
    b"\xff\xd8\xff" + b"x" * checks.PHOTO_BYTES).decode()
# A broken JPEG, and one that claims more pixels than any phone photo, are refused too.
broken = as_photo(jpeg(400, 300)[:300])["photo"]
too_wide = as_photo(jpeg(checks.PHOTO_SIDE + 1, 8))["photo"]
for bad in (png, not_jpeg, too_big, broken, too_wide, "data:image/jpeg;base64,not base64!",
            42, ""):
    refused = client.post(shot_entry, headers=KEY, json={"photo": bad})
    assert refused.status_code == 400, (str(bad)[:40], refused.status_code)
huge = client.post(shot_entry, headers=KEY, json={"photo": "x" * 1_100_000})
assert huge.status_code == 413 and "too big" in huge.get_json()["error"], huge.status_code
assert status_of(shot) == "approved", "a refused photo lets nobody in"
# A pass that cannot enter is refused for that reason, not for the photo.
assert client.post(f"/api/pass/{exit_of(shot)}/entry", headers=KEY).status_code == 409
# The phone's details, such as its maker or a location, never reach the database.
with_details = Image.Exif()
with_details[0x010F] = "PhoneMaker"
let_in = client.post(shot_entry, headers=KEY, json=as_photo(jpeg(exif=with_details)))
assert let_in.status_code == 200, let_in.get_json()
stored = entries.photo_of(shot["reference"])
assert is_clean_photo(stored["image"]) and stored["media_id"] is None
assert b"PhoneMaker" not in stored["image"]
assert stored["taken_at"] == visits.get(shot["reference"])["entered_at"]

# The photo is for the admin only. No gate, visitor or log answer holds it.
stored_photo = checks.PHOTO_PREFIX + base64.b64encode(stored["image"]).decode()
encoded = stored_photo.split(",")[1]
for path, headers in ((f"/api/pass/{exit_of(shot)}", KEY), (f"/api/pass/{shot['reference']}", KEY),
                      ("/api/gate/board", KEY), (f"/api/visit/{shot['token']}", {}),
                      ("/api/admin/export.csv", ADMIN),
                      (f"/api/admin/visits?q={shot['reference']}", ADMIN)):
    assert encoded not in client.get(path, headers=headers).get_data(as_text=True), path
listed = client.get(f"/api/admin/visits?q={shot['reference']}", headers=ADMIN).get_json()
assert listed["visits"][0]["photo_stored"] is True
photo_path = f"/api/admin/photo/{shot['reference']}"
assert client.get(photo_path, headers=KEY).status_code == 403, "the gate key opens no photo"
assert client.get(photo_path).status_code == 403
viewed = client.get(photo_path, headers=ADMIN)
assert viewed.status_code == 200 and viewed.get_json()["photo"] == stored_photo
assert viewed.headers["Cache-Control"] == "no-store"
assert client.get("/api/admin/photo/VR-0000", headers=ADMIN).status_code == 404
# A WhatsApp photo stays in the chat, so there is nothing to show.
by_chat = approved()
say(APPROVER, f"IN {entry_of(by_chat)}")
snap(APPROVER)
assert status_of(by_chat) == "inside"
assert client.get(f"/api/admin/photo/{by_chat['reference']}", headers=ADMIN).status_code == 404
visits.delete(shot["reference"])
assert entries.photo_of(shot["reference"]) is None, "the photo goes with its visit"
print("  no photo, a wrong file or a big file is refused, the admin alone sees the photo")

print("guards added on the admin page have their own key, and the log names them")
limits.forget_hits()
RAVI_PHONE = "+919800000001"
RAVI = RAVI_PHONE[1:]
RAVI_LABEL = f"Ravi {RAVI_PHONE}"


def add(guard_name, guard_phone, with_key=None):
    return client.post("/api/admin/guards", json={"name": guard_name, "phone": guard_phone},
                       headers=with_key or ADMIN)


bad = add("", "123")
assert bad.status_code == 400 and set(bad.get_json()["fields"]) == {"name", "phone"}, bad.get_json()
assert add("Desk", config.GUARD).status_code == 400, "the gate desk is a guard already"
assert add("Admin", config.ADMIN_PHONE).status_code == 400, "a guard must not get the admin key"
assert add("Long" * 20, RAVI_PHONE).status_code == 400
assert add("Ravi", RAVI_PHONE, with_key=KEY).status_code == 403, "the gate key adds no guard"
added = add("Ravi", RAVI_PHONE)
assert added.status_code == 200, added.get_json()
ravi_key = added.get_json()["key"]
assert len(ravi_key) >= 20 and "key_hash" not in added.get_data(as_text=True)
assert add("Ravi again", RAVI_PHONE).status_code == 400, "one number, one guard"
summary = client.get("/api/admin/summary", headers=ADMIN).get_json()
assert summary["gate_desk"] == config.GUARD
assert [g["phone"] for g in summary["guards"]] == [RAVI_PHONE], summary["guards"]
assert "key_hash" not in str(summary)
with db.connect() as conn:
    stored = conn.execute("SELECT key_hash FROM guards").fetchone()["key_hash"]
assert stored == people.key_hash(ravi_key) and ravi_key not in stored, "only the hash is kept"

# The gate page knows the guard by their key, and records who let the visitor in.
RAVI_KEY = {"X-Gate-Key": ravi_key}
assert client.get("/api/gate/board", headers=RAVI_KEY).get_json()["you"] == RAVI_LABEL
assert client.get("/api/gate/board", headers=KEY).get_json()["you"] == access.DESK_KEY
by_page = approved()
let_in = client.post(f"/api/pass/{entry_of(by_page)}/entry", headers=RAVI_KEY, json=PHOTO)
assert let_in.status_code == 200, let_in.get_json()
assert RAVI_PHONE not in let_in.get_data(as_text=True), "a guard never sees a guard's number"
assert visits.get(by_page["reference"])["entered_by"] == RAVI_LABEL
assert RAVI_PHONE not in client.get(f"/api/visit/{by_page['token']}").get_data(as_text=True)
assert client.post(f"/api/pass/{exit_of(by_page)}/exit", headers=KEY).status_code == 200
assert visits.get(by_page["reference"])["exited_by"] == access.DESK_KEY
listed = client.get(f"/api/admin/visits?q={by_page['reference']}", headers=ADMIN).get_json()
assert listed["visits"][0]["entered_by"] == RAVI_LABEL
assert listed["visits"][0]["exited_by"] == access.DESK_KEY
assert RAVI_PHONE in client.get("/api/admin/export.csv", headers=ADMIN).get_data(as_text=True)

# On WhatsApp the guard's own number lets visitors in and out.
by_phone = approved()
say(RAVI, f"IN {entry_of(by_phone)}")
assert "Inside now" in snap(RAVI)
assert visits.get(by_phone["reference"])["entered_by"] == RAVI_LABEL
assert "Closed" in say(RAVI, f"OUT {exit_of(by_phone)}")
assert visits.get(by_phone["reference"])["exited_by"] == RAVI_LABEL
print("  own key works, only its hash kept, entry and exit name the guard, visitor sees nothing")

print("every guard hears about an approval, never with a gate code")
sent.clear()
told = new_request()
assert "is now approved" in say(APPROVER, f"YES {told['reference']}"), "the reply stays last"
to_ravi = [body for to, body in sent if whatsapp.same_number(to, RAVI)]
assert len(to_ravi) == 1 and told["reference"] in to_ravi[0], to_ravi
assert not any(code in to_ravi[0] for code in visits.codes_of(told["reference"]).values())
to_approver = [body for to, body in sent if whatsapp.same_number(to, APPROVER)]
assert not any("Approved visitor" in body for body in to_approver), "the approver is not told again"
sent.clear()
say(APPROVER, f"NO {new_request()['reference']}")
assert not any(whatsapp.same_number(to, RAVI) for to, _ in sent), "a decline tells no guard"
sent.clear()
auto = new_request()
with db.connect() as conn:
    conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", auto["reference"]))
db.forget_cache()
timer.auto_approve_due()
assert [to for to, body in sent if auto["reference"] in body and "Approved visitor" in body] \
    == [RAVI_PHONE], sent
print("  told once on approval and automatic approval, not on a decline, no code")

print("a guard's key is renewed by KEY or by the admin, and removal stops everything")
fresh_reply = say(RAVI, "KEY")
assert GATE_KEY_TEXT not in fresh_reply and ADMIN_KEY_TEXT not in fresh_reply
ravi_key2 = fresh_reply.split("\n")[1]
assert client.get("/api/gate/board", headers=RAVI_KEY).status_code == 403, "the old key stops"
assert client.get("/api/gate/board", headers={"X-Gate-Key": ravi_key2}).status_code == 200
renewed = client.post("/api/admin/guards/new-key", json={"phone": RAVI_PHONE}, headers=ADMIN)
ravi_key3 = renewed.get_json()["key"]
assert client.get("/api/gate/board", headers={"X-Gate-Key": ravi_key2}).status_code == 403
assert client.get("/api/gate/board", headers={"X-Gate-Key": ravi_key3}).status_code == 200
assert client.post("/api/admin/guards/new-key", json={"phone": "+919800000999"},
                   headers=ADMIN).status_code == 404
removed = client.post("/api/admin/guards/remove", json={"phone": RAVI_PHONE}, headers=ADMIN)
assert removed.get_json()["guards"] == []
assert client.get("/api/gate/board", headers={"X-Gate-Key": ravi_key3}).status_code == 403
sent_before = len(sent)
client.post("/webhook/whatsapp", json=inbound(RAVI, f"IN {entry_of(approved())}"))
assert not any(whatsapp.same_number(to, RAVI) for to, _ in sent[sent_before:]), \
    "a removed guard gets no reply and no update"
assert visits.get(by_page["reference"])["entered_by"] == RAVI_LABEL, "the log keeps the name"
assert client.post("/api/admin/guards/remove", json={"phone": RAVI_PHONE},
                   headers=ADMIN).status_code == 404
print("  KEY and the admin each make a new key, the old one stops, removal ends access")

# Last, because it closes the database for the rest of this process.
print("on exit, the timer stops and the database closes before Python shuts down")
overdue = new_request()
with db.connect() as conn:
    conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", overdue["reference"]))
db.forget_cache()
application.start_background()
assert timer.background.is_alive()
# The first round runs at once, so a request due while the server slept is approved on wake.
for _ in range(50):
    if visits.get(overdue["reference"])["status"] == "approved":
        break
    timer.stopping.wait(0.1)
assert visits.get(overdue["reference"])["status"] == "approved", "the first round must not wait"
started = time.monotonic()
application.stop_background()
assert time.monotonic() - started < 3, "exit must not wait out the timer's sleep"
application.stop_background()
assert not timer.background.is_alive(), "the timer must stop"
try:
    db.connect()
    raise AssertionError("a closed database must not open a new pool on the way out")
except RuntimeError:
    pass
print("  timer stopped, pool closed, safe to call twice")

print()
print("all checks passed")

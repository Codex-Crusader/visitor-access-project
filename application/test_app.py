"""End to end check with the WhatsApp call stubbed out.

Run it with: .venv\\Scripts\\python.exe test_app.py
It sends no WhatsApp messages and uses a throwaway database.
"""

import contextlib
import logging
import os
import re
from datetime import datetime, timezone

import psycopg
from psycopg_pool import PoolTimeout

import testdb

os.environ.update(
    META_TOKEN="test-token",
    META_PHONE_NUMBER_ID="100000000000000",
    META_VERIFY_TOKEN="visitor-access-verify",
    META_APP_SECRET="",
    MAIN_APPROVER="+911234567890",
    BACKUP_APPROVER="+911234567890",
    GUARD="+911234567890",
    GATE_KEY="test-gate-key",
    ADMIN_KEY="test-admin-key",
    GATE_DESK_PHONE="+912200000000",
    ESCALATE_MINUTES="30",
    RETAIN_DAYS="1",
    DATABASE_URL=testdb.url(),
)

import app as application
import config
import db
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
client = application.app.test_client()
KEY = {"X-Gate-Key": "test-gate-key"}
ADMIN = {"X-Admin-Key": "test-admin-key"}
# A gate code: two letters without I or O, a dash, four digits.
GATE_CODE = re.compile(r"^[A-HJ-NP-Z]{2}-\d{4}$")


def entry_of(made):
    """The entry code. The server and the visitor's pass are the only holders."""
    return db.codes_of(made["reference"])["entry"]


def exit_of(made):
    return db.codes_of(made["reference"])["exit"]


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
    made = client.post("/api/requests", json=payload)
    assert made.status_code == 201, made.get_data(as_text=True)
    return made.get_json()


print("visitor flow")
visit = new_request()
code, token = visit["reference"], visit["token"]
assert visit["status"] == "pending"
assert len(token) > 16, "token must be long enough to resist guessing"
assert code in sent[-1][1]
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
    refused_request = client.post("/api/requests", json=payload)
    assert refused_request.status_code == 502, refused_request.status_code
    assert len(sent) == sent_before, "no plain text may go out without the fallback"

    # The backup approver's round fails the same way, and one failure stops
    # neither the other escalations nor the purge after them.
    with db.connect() as conn:
        conn.execute("UPDATE visits SET created_at = %s WHERE status = 'pending'",
                     ("2020-06-01T00:00:00+00:00",))
    caught.clear()
    application.escalate_due()
    assert any("backup approver" in line for line in caught), caught
    assert db.due_for_escalation(), "a failed escalation must stay due and be tried again"
    with db.connect() as conn:
        conn.execute("UPDATE visits SET created_at = %s WHERE created_at = %s",
                     (db.now(), "2020-06-01T00:00:00+00:00"))

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
application.forget_hits()
letters = {entry_of(new_request())[:2] for _ in range(12)}
application.forget_hits()
assert len(letters) > 1, letters
# The generator itself: 2000 codes, no I or O to misread as 1 or 0, never VR.
made_codes = [db.new_gate_code() for _ in range(2000)]
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
assert client.get(f"/api/visit/{token}").get_json()["status"] == "pending"

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
print("  duplicate delivery ignored")

assert "already approved" in say(APPROVER, f"NO {code}")
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
assert db.photo_of(code)["taken_at"] == entered["entered_at"]
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
    made = new_request()
    say(APPROVER, f"YES {made['reference']}")
    return made


def status_of(made):
    return client.get(f"/api/visit/{made['token']}").get_json()["status"]


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
late = snap(APPROVER)
assert "No entry is waiting" in late and str(application.PHOTO_MINUTES) in late, late
assert status_of(first) == "approved"

# The web gate let the visitor in while the guard was taking the photo.
say(APPROVER, f"IN {entry_of(first)}")
client.post(f"/api/pass/{entry_of(first)}/entry", headers=KEY)
assert "Already inside" in snap(APPROVER)
assert db.photo_of(first["reference"]) is None

# A photo from a stranger gets no answer and changes nothing.
third = approved()
say(APPROVER, f"IN {entry_of(third)}")
assert snap(STRANGER) == ""
assert status_of(third) == "approved"

# An approver who is not the gate desk cannot let anyone in with a photo.
real_guard = application.config.GUARD
application.config.GUARD = "+919999999999"
try:
    assert "Only the gate desk" in snap(APPROVER)
finally:
    application.config.GUARD = real_guard

# A failure after the message id is spent asks for the photo again, and the
# photo sent again then works, because nothing was used up.
real_enter = db.enter_with_photo


def broken(*_args):
    raise RuntimeError("database is locked")


db.enter_with_photo = broken
try:
    assert "Send that again" in snap(APPROVER)
finally:
    db.enter_with_photo = real_enter
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
assert client.post(f"/api/pass/{ref2}/entry", headers=KEY).status_code == 404
wrong_kind = client.post(f"/api/pass/{exit2}/entry", headers=KEY)
assert wrong_kind.status_code == 409 and "exit code" in wrong_kind.get_json()["error"]
assert client.post(f"/api/pass/{exit2}/exit", headers=KEY).status_code == 409
entered = client.post(f"/api/pass/{entry2}/entry", headers=KEY)
assert entered.status_code == 200 and entered.get_json()["status"] == "inside"
assert exit2 not in entered.get_data(as_text=True)
assert client.post(f"/api/pass/{entry2}/entry", headers=KEY).status_code == 409
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
refused_body = client.post(f"/api/pass/{entry2}/entry", headers=KEY).get_json()
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
    assert open_pass[field], field
assert "code_kind" not in open_pass
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
                    "decided_at", "entered_at"}, set(shown)
# The board is the one list every guard sees. It must hold no gate code.
board_text = client.get("/api/gate/board", headers=KEY).get_data(as_text=True)
assert not any(c in board_text for c in (entry_of(live), exit_of(live),
                                        entry_of(second_in), exit_of(second_in)))
# Inside is ordered longest first, so whoever never left is at the top.
entered = [v["entered_at"] for v in board["inside"]]
assert entered == sorted(entered), entered
# A pass approved more than BOARD_HOURS ago leaves the list but still works.
with db.connect() as conn:
    conn.execute("UPDATE visits SET decided_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", live["reference"]))
board = client.get("/api/gate/board", headers=KEY).get_json()
assert live["reference"] not in [v["reference"] for v in board["expected"]]
assert client.get(f"/api/pass/{live['reference']}", headers=KEY).get_json()["status"] == "approved"
print(f"  {len(board['inside'])} inside, {len(board['expected'])} expected")

print("a declined pass never opens the gate")
bad = new_request()
say(APPROVER, f"NO {bad['reference']}")
refused = client.post(f"/api/pass/{entry_of(bad)}/entry", headers=KEY)
assert refused.status_code == 409 and "Declined" in refused.get_json()["error"]

print("several waiting requests")
a, b = new_request(), new_request()
many = say(APPROVER, "YES")
assert "These requests are waiting" in many
assert a["reference"] in many and b["reference"] in many and "Asha Rao" in many
say(APPROVER, f"YES {a['reference']}")
assert client.get(f"/api/visit/{a['token']}").get_json()["status"] == "approved"

print("escalation never decides, it only asks again")
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", b["reference"]))
due = db.due_for_escalation()
assert [v["reference"] for v in due] == [b["reference"]], due
whatsapp.notify_backup(due[0], db.approvers_for(db.approver_table(), due[0]["reason"]))
db.mark_escalated(b["reference"])
after = client.get(f"/api/visit/{b['token']}").get_json()
assert after["status"] == "escalated" and after["escalated_at"]
assert "Backup approver" in sent[-1][1]
assert templates[-1][0] == "+911234567890" and templates[-1][1][1].startswith("Backup")
# An escalated request is still undecided, and a visitor inside never escalates.
assert b["reference"] in [v["reference"] for v in db.open_requests()]
assert ref2 not in [v["reference"] for v in db.open_requests()]
assert ref2 not in [v["reference"] for v in db.due_for_escalation()]

print("retention deletes records older than RETAIN_DAYS")
old = new_request()
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", old["reference"]))
old_entry = entry_of(old)
assert db.purge_old() >= 1
assert db.get(old["reference"]) is None
# Its codes go with it, so a purged pass can never be looked up again.
assert db.codes_of(old["reference"]) == {}
assert db.by_code(old_entry) == (None, None)
assert client.get(f"/api/visit/{old['token']}").status_code == 404
# Today's records survive the purge.
assert db.get(a["reference"]) is not None
# A photo goes with its visit, and the photos of kept visits stay.
gone, kept = new_request(), new_request()
with db.connect() as conn:
    for photographed in (gone, kept):
        conn.execute("INSERT INTO photos (reference, media_id, taken_at) VALUES (%s, %s, %s)",
                     (photographed["reference"], "media.x", db.now()))
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", gone["reference"]))
db.purge_old()
assert db.photo_of(gone["reference"]) is None
assert db.photo_of(kept["reference"]) is not None
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
    assert db.get(delivery["reference"])["status"] == "pending"
    wrong = say(DELIVERY_MAIN[1:], f"YES {student['reference']}")
    assert "another approver" in wrong, wrong
    # Each approver's waiting list holds only their own reasons.
    table = db.approver_table()
    waiting_delivery = [v["reference"] for v in application.waiting_for(DELIVERY_MAIN, table)]
    assert waiting_delivery == [delivery["reference"]], waiting_delivery
    assert delivery["reference"] not in [
        v["reference"] for v in application.waiting_for(APPROVER, table)]
    # The backup for the reason can decide it, before or after escalation.
    assert "is now approved" in say(DELIVERY_BACKUP[1:], f"YES {delivery['reference']}")
    assert db.get(delivery["reference"])["status"] == "approved"
    assert db.get(delivery["reference"])["decided_by"] == db.BY_BACKUP

    # Escalation goes to the backup of the request's own reason.
    late = client.post("/api/requests", json={**payload, "reason": "Delivery"}).get_json()
    with db.connect() as conn:
        conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                     (db.ago(1 / 24), late["reference"]))
    application.escalate_due()
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
    assert client.get(path, headers={"X-Admin-Key": "test-gate-key"}).status_code == 403, path
assert client.get("/admin").status_code == 200
# With no ADMIN_KEY, or the gate key as ADMIN_KEY, the admin page is locked.
# Either one would otherwise let the guards in. The rest of the app runs.
for bad_key in ("", "test-gate-key", " test-gate-key "):
    os.environ["ADMIN_KEY"] = bad_key
    locked_key, why = config.read_admin_key()
    assert locked_key == "" and "ADMIN_KEY" in why, (bad_key, why)
os.environ["ADMIN_KEY"] = "test-admin-key"
assert config.read_admin_key() == ("test-admin-key", "")
# Locked, every admin call is refused, even an empty key that would match an
# empty ADMIN_KEY, and even the right key from before.
real_admin = config.ADMIN_KEY, config.ADMIN_LOCKED
os.environ["ADMIN_KEY"] = ""
config.ADMIN_KEY, config.ADMIN_LOCKED = config.read_admin_key()
try:
    for path in ("/api/admin/visits", "/api/admin/summary", "/api/admin/export.csv"):
        for headers in ({}, {"X-Admin-Key": ""}, {"X-Admin-Key": "test-gate-key"}, ADMIN):
            locked = client.get(path, headers=headers)
            assert locked.status_code == 503, (path, headers, locked.status_code)
            assert "ADMIN_KEY" in locked.get_json()["error"], path
    # The gate and the visitor form do not depend on the admin key.
    assert client.get("/api/gate/board", headers=KEY).status_code == 200
finally:
    os.environ["ADMIN_KEY"] = "test-admin-key"
    config.ADMIN_KEY, config.ADMIN_LOCKED = real_admin

# More than one page of visits. The rate limit would refuse some of them.
for number in range(60):
    application.forget_hits()
    page_request = client.post("/api/requests", json={**payload, "name": f"Page Test {number}"})
    assert page_request.status_code == 201, page_request.get_data(as_text=True)
application.forget_hits()
total = sum(db.status_counts().values())
seen, cursor, pages = [], None, 0
while True:
    query = f"/api/admin/visits?after={cursor}" if cursor else "/api/admin/visits"
    page = client.get(query, headers=ADMIN).get_json()
    pages += 1
    for row in page["visits"]:
        # The token is the visitor's private status link. It never leaves.
        assert "token" not in row, row
        assert row["approvers"] == list(db.approvers_for(db.approver_table(), row["reason"]))
    seen += [row["reference"] for row in page["visits"]]
    cursor = page["next"]
    if not cursor:
        break
    cursor = cursor.replace("+", "%2B")
assert len(seen) == len(set(seen)) == total, (len(seen), len(set(seen)), total)
assert pages == -(-total // application.ADMIN_PAGE), pages
times = [db.get(r)["created_at"] for r in seen]
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
                      ("/api/admin/summary", ADMIN), ("/api/admin/export.csv", ADMIN),
                      ("/api/export.csv", KEY)):
    answer = client.get(path, headers=headers).get_data(as_text=True)
    assert not any(c in answer for c in live_codes), path
print(f"  {total} visits over {pages} pages, none twice, none missed, no token, no code")

print("pages are served")
for path in ("/", "/app.js", "/gate", "/gate.js", "/admin", "/admin.js", "/shared.js", "/sw.js"):
    assert client.get(path).status_code == 200, path
cfg = client.get("/api/config").get_json()
assert cfg["escalate_minutes"] == 30 and cfg["retain_days"] == 1
assert "gate_key" not in str(cfg).lower(), "the gate key must never be published"

print("export of every entry and exit")
# Needs the gate key, same as the rest of the gate.
assert client.get("/api/export.csv").status_code == 403
assert client.get("/api/export.csv", headers={"X-Gate-Key": "wrong"}).status_code == 403

dump = client.get("/api/export.csv", headers=KEY)
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
# The log says when the gate photo was taken. The web gate takes none.
assert done[0]["photo_at"] == "", done[0]
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
armed = client.get("/api/export.csv", headers=KEY).get_data(as_text=True)
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
application.forget_hits()

# Creating requests is capped so a stranger cannot spam the approver's phone.
codes_before = len(db.all_visits())
limit = __import__("config").REQUESTS_PER_HOUR
statuses = [client.post("/api/requests", json=payload).status_code for _ in range(limit + 5)]
assert statuses.count(201) == limit, statuses
assert statuses.count(429) == 5, statuses
print(f"  request flood: {statuses.count(201)} allowed, {statuses.count(429)} refused")

# Wrong gate keys are always refused.
application.forget_hits()
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
application.forget_hits()
for i in range(20):
    client.post("/api/requests", json={**payload, "phone": "123"},
                headers={"X-Forwarded-For": f"9.9.9.{i}"})
buckets = application.hit_buckets()
assert buckets == 1, f"spoofed headers created {buckets} buckets"
print("  20 calls behind 20 fake addresses still counted as one caller")

# The limit must never block Meta's webhook, which shares no bucket with the gate.
application.forget_hits()
fresh = new_request()
for _ in range(70):
    client.get("/api/pass/VR-0001", headers={"X-Gate-Key": "guess"})
ok = client.post("/webhook/whatsapp", json=inbound(APPROVER, f"YES {fresh['reference']}"))
assert ok.status_code == 200
assert client.get(f"/api/visit/{fresh['token']}").get_json()["status"] == "approved"
print("  webhook still works while the gate is rate limited")

# A visitor polling their own status is never rate limited.
application.forget_hits()
polls = [client.get(f"/api/visit/{fresh['token']}").status_code for _ in range(50)]
assert set(polls) == {200}, set(polls)
print("  50 visitor polls all served")

# The table of callers stays bounded. Callers silent for an hour are dropped
# once it passes MAX_CALLERS, and callers heard from recently are kept.
application.forget_hits()
application.add_silent_callers(application.MAX_CALLERS + 1, 7200)
assert client.post("/api/requests", json={**payload, "phone": "123"}).status_code == 400
assert application.hit_buckets() == 1, application.hit_buckets()
print(f"  {application.MAX_CALLERS + 1} silent callers swept out, the live one kept")
application.forget_hits()

print("migrations run once, so a restart keeps every visit")
kept_visit = new_request()
assert db.init() == len(db.MIGRATIONS)
assert db.init() == len(db.MIGRATIONS)
with db.connect() as conn:
    versions = [row["version"] for row in
                conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
assert versions == list(range(1, len(db.MIGRATIONS) + 1)), versions
assert db.get(kept_visit["reference"]) is not None
# A step added later runs on the next start, and the visits stay.
db.MIGRATIONS.append("ALTER TABLE visits ADD COLUMN test_note TEXT")
try:
    assert db.init() == len(db.MIGRATIONS)
    assert db.get(kept_visit["reference"])["test_note"] is None
finally:
    db.MIGRATIONS.pop()
print(f"  schema at version {len(db.MIGRATIONS)}, a new column added, visits kept")

print("scripts are cached by version, pages are checked")
for path, script in (("/", "app.js"), ("/gate", "gate.js"), ("/admin", "admin.js")):
    shown = client.get(path)
    assert shown.headers["Cache-Control"] == "no-cache", shown.headers
    address = f"{script}?v={application.SCRIPT_VERSIONS[script]}"
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
        ("entry", lambda: client.post(f"/api/pass/{counted_code}/entry", headers=KEY), 2),
    ):
        trips.clear()
        assert call().status_code == 200, label
        assert len(trips) <= most, (label, len(trips))
finally:
    db.connect = real_connect
print("  status check 1, pass lookup 1, entry 2")

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
assert db.get(kept_visit["reference"])["reference"] == kept_visit["reference"]

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
    assert db.init() == len(db.MIGRATIONS) and len(fails) == 3
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
assert db.get(event["reference"])["decided_by"] == db.BY_MAIN
with db.connect() as conn:
    conn.execute("DELETE FROM approvers")
print("  both numbers required and checked, new number used at once, old one refused")

print("a request made in working hours is approved by itself")


def ist(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=config.WORK_TIMEZONE)


# Monday 5, Saturday 10 and Sunday 11 October 2026.
assert application.auto_approve_time(ist(5, 9, 59)) is None
assert application.auto_approve_time(ist(5, 10)) == "2026-10-05T05:00:00+00:00"
assert application.auto_approve_time(ist(5, 16, 59)) == "2026-10-05T11:59:00+00:00"
assert application.auto_approve_time(ist(5, 17)) is None
assert application.auto_approve_time(ist(10, 12)) is not None
assert application.auto_approve_time(ist(11, 12)) is None
# 04:30 UTC is 10:00 in India, so it counts.
assert application.auto_approve_time(datetime(2026, 10, 5, 4, 30, tzinfo=timezone.utc)) \
    == "2026-10-05T05:00:00+00:00"

due, with_backup, declined, not_yet = (new_request() for _ in range(4))
with db.connect() as conn:
    for case, moment in ((due, "2020-01-01T00:00:00+00:00"),
                         (with_backup, "2020-01-01T00:00:00+00:00"),
                         (declined, "2020-01-01T00:00:00+00:00"),
                         (not_yet, "2999-01-01T00:00:00+00:00")):
        conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                     (moment, case["reference"]))
db.mark_escalated(with_backup["reference"])
say(APPROVER, f"NO {declined['reference']}")
before = len(sent)
application.auto_approve_due()
for case in (due, with_backup):
    got = db.get(case["reference"])
    assert got["status"] == "approved" and got["decided_by"] == db.BY_AUTO, got
assert db.get(declined["reference"])["status"] == "declined"
assert db.get(not_yet["reference"])["status"] == "pending"
notices = [body for _, body in sent[before:] if "approved automatically" in body]
assert len(notices) == 2, notices
application.auto_approve_due()
assert len(sent) == before + 2, "a second round must not approve or notify again"
view = client.get(f"/api/visit/{due['token']}").get_json()
assert view["status"] == "approved" and view["decided_by"] == "auto" and view["entry_code"]
print("  10:00 to 16:59 Monday to Saturday only, a NO first wins, approvers told once")

print("a forgotten key goes to its own number, never to the page")
application.forget_hits()
sent.clear()
gate_reply = client.post("/api/forgot-key/gate")
assert gate_reply.get_json() == {"sent_to": whatsapp.digits(config.GUARD)[-4:]}
assert sent[-1][0] == config.GUARD and "test-gate-key" in sent[-1][1]
assert "test-gate-key" not in gate_reply.get_data(as_text=True)
admin_reply = client.post("/api/forgot-key/admin")
assert admin_reply.status_code == 200
assert sent[-1][0] == config.ADMIN_PHONE and "test-admin-key" in sent[-1][1]
assert "test-admin-key" not in admin_reply.get_data(as_text=True)
assert client.post("/api/forgot-key/wifi").status_code == 404
client.post("/api/forgot-key/gate")
client.post("/api/forgot-key/gate")
assert client.post("/api/forgot-key/gate").status_code == 429
# Ten tries an hour in all, even from many addresses.
application.forget_hits()
config.BEHIND_PROXY = True
try:
    codes = [client.post("/api/forgot-key/admin",
                         headers={"X-Forwarded-For": f"10.0.0.{n}"}).status_code
             for n in range(11)]
finally:
    config.BEHIND_PROXY = False
    application.forget_hits()
assert codes == [200] * 10 + [429], codes
# KEY on WhatsApp answers only the numbers that hold a key.
assert "test-gate-key" in say(APPROVER, "KEY")
sent_before = len(sent)
client.post("/webhook/whatsapp", json=inbound(STRANGER, "KEY"))
assert len(sent) == sent_before, "a stranger must get no reply"
print("  sent to the fixed number, 3 tries per caller and 10 in all each hour, KEY works")

# Last, because it closes the database for the rest of this process.
print("on exit, the timer stops and the database closes before Python shuts down")
application.start_background()
assert application.background.is_alive()
application.stop_background()
application.stop_background()
assert not application.background.is_alive(), "the timer must stop"
try:
    db.connect()
    raise AssertionError("a closed database must not open a new pool on the way out")
except RuntimeError:
    pass
print("  timer stopped, pool closed, safe to call twice")

print()
print("all checks passed")

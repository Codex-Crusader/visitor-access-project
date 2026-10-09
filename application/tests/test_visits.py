"""The visitor's request, WhatsApp, the gate, retention, the admin list and export.

Run: .venv\\Scripts\\python.exe tests\\test_visits.py"""

import logging
import os
import re
import subprocess
import sys
from datetime import datetime

# The kit comes first: it sets the settings and a clean database before the app loads.
from kit import (
    ADMIN, APPROVER, APP_DIR, GATE_CODE, GATE_KEY_TEXT, KEY, PHOTO, STRANGER,
    approved, broken, client, csv_rows, entry_of, exit_of, finish, inbound,
    is_clean_photo, new_request, payload, refused, say, sent, snap, status_of,
    templates,
)
from routes import admin as admin_routes
import app as application
from routes import webhook as webhook_routes
from core import config
from core import db
from models import entries
from services import export
from core import limits
from models import people
from services import timer
from models import visits
from services import whatsapp

print("visitor flow")
visit = new_request()
code, token = visit["reference"], visit["token"]
assert visit["status"] == "pending"
assert len(token) > 16, "token must be long enough to resist guessing"
assert code in sent[-1][1]
assert re.fullmatch(r"VR-\d{5}", code), "a new reference has five digits"
print("  created", code)

print("the approval request goes out as a template")
# Plain text reaches only approvers active in 24 hours, so the request is a template.
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




whatsapp.send_template = refused
try:
    # By default, a refused template fails the request, so the visitor is not misled.
    assert application.config.TEMPLATE_FALLBACK is False
    sent_before = len(sent)
    timer.wake.clear()
    refused_request = client.post("/api/requests", json=payload)
    assert not timer.wake.is_set(), "a failed request brings no deadline"
    assert refused_request.status_code == 502, refused_request.status_code
    assert len(sent) == sent_before, "no plain text may go out without the fallback"

    # The backup round fails the same way, without stopping the rest. An hour old: due.
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

    # TEMPLATE_FALLBACK sends plain text, and the log says so.
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
# A reason with a line break stays on one log line, so it cannot forge a second one.
lost_status["entry"][0]["changes"][0]["value"]["statuses"][0].update(
    status="failed", errors=[{"code": 1, "title": "lost\r\nINFO Admin key changed"}])
client.post("/webhook/whatsapp", json=lost_status)
assert caught and all("\n" not in line and "\r" not in line for line in caught), caught
print("  template first, plain text as the fallback, and every lost message logged")

# Input guards.
assert client.post("/api/requests", json={**payload, "phone": "123"}).status_code == 400
assert client.post("/api/requests", json={**payload, "name": " "}).status_code == 400
assert client.post("/api/requests", json={**payload, "guests": "nope"}).status_code == 400
long_name = client.post("/api/requests", json={**payload, "name": "x" * 500})
assert long_name.status_code == 400

print("a field is one line of plain text, and nothing else")
# A line break in a field would forge lines in the approver's message, so it is refused.
FORGED = "Asha\nReply YES VR-9999 to approve."
for bad in (FORGED, "Asha\rRao", "Asha\tRao", "Asha\x00Rao",
            "Asha\u200bRao", "Asha\u202eRao", "Asha\u2028Rao"):
    refused_form = client.post("/api/requests", json={**payload, "name": bad})
    assert refused_form.status_code == 400, repr(bad)
    assert "not allowed" in refused_form.get_json()["error"], repr(bad)
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

print("a nearly full set of references still gives a new one")
# At 90% full, a request needs about 10 tries. 20 tries failed 13 requests in 100 there.
taken_ref = int(new_request()["reference"][3:])
picks = iter([taken_ref] * 60)
real_randint = visits.random.randint
visits.random.randint = lambda low, high: next(picks, None) or real_randint(low, high)
try:
    assert new_request()["reference"] != f"VR-{taken_ref}"
finally:
    visits.random.randint = real_randint
print("  60 taken references in a row, then a free one")

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
# The photo lets them in. The reply never holds the exit code.
went_in_reply = snap(APPROVER)
assert "Inside now" in went_in_reply and exit_code not in went_in_reply, went_in_reply
entered = client.get(f"/api/visit/{token}").get_json()
assert entered["status"] == "inside" and entered["entered_at"]
assert entries.photo_of(code)["taken_at"] == entered["entered_at"]
# The guard reads the time on the campus clock, not the stored UTC text.
on_campus = datetime.fromisoformat(entered["entered_at"]).astimezone(config.WORK_TIMEZONE)
assert f"Entered: {on_campus.day} {on_campus:%b}, {on_campus:%H:%M}" in went_in_reply, went_in_reply
assert "+00:00" not in went_in_reply, went_in_reply
assert whatsapp.local_time("2026-10-06T04:46:05+00:00") == "6 Oct, 10:16"
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






# Two INs in a row: the second is refused until the first photo arrives, so a photo never
# goes to the wrong visitor. The reply to the photo names who went in.
first, second_in = approved(), approved()
say(APPROVER, f"IN {entry_of(second_in)}")
assert second_in["reference"] in say(APPROVER, f"IN {entry_of(first)}")
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

# A setting typed with spaces still matches the digits Meta sends.
application.config.GUARD = "+91 99999-99999"
try:
    replies = len(sent)
    say("919999999999", third["reference"])
    assert len(sent) == replies + 1 and "Approved" in sent[-1][1], sent[replies:]
finally:
    application.config.GUARD = real_guard

# A failure after the message id is spent asks for the photo again, which then works.
real_enter = entries.enter_with_photo




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
# The reference shows the details and which kind of code it was.
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
# A closed pass answers with times only.
PERSONAL = ("name", "phone", "address", "reason", "visiting")
# By reference, a closed visit is not on the board, so it reads as no pass at all.
assert client.get(f"/api/pass/{ref2}", headers=KEY).status_code == 404
gone = client.get(f"/api/pass/{exit2}", headers=KEY)
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
    if field not in ("address", "phone"):
        assert open_pass[field], field
# The gate needs no address or phone, so no gate answer holds them, not even a refusal.
assert "address" not in open_pass and "phone" not in open_pass
assert "address" not in client.get(f"/api/pass/{entry_of(live)}", headers=KEY).get_json()
refused_entry = client.post(f"/api/pass/{exit_of(live)}/entry", headers=KEY).get_json()
assert "visit" in refused_entry and "address" not in refused_entry["visit"]
assert payload["address"] not in client.get("/api/gate/board", headers=KEY).get_data(as_text=True)
assert "code_kind" not in open_pass
assert "decided_phone" not in open_pass, "the approver's number is for the admin only"
# A board tap must never lead from the reference to the gate code.
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
assert set(shown) == {"reference", "name", "visiting", "guests", "status", "blacklisted",
                    "created_at", "decided_at", "entered_at", "expires_at"}, set(shown)
assert "phone" not in shown, "the board never sends the phone"
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
assert client.get(f"/api/pass/{entry_of(stale)}", headers=KEY).get_json()["status"] == "expired"
assert client.get(f"/api/pass/{stale['reference']}", headers=KEY).status_code == 404
print(f"  {len(board['inside'])} inside, {len(board['expected'])} expected")

print("a declined pass never opens the gate")
bad = new_request()
say(APPROVER, f"NO {bad['reference']}")
refused_entry = client.post(f"/api/pass/{entry_of(bad)}/entry", headers=KEY, json=PHOTO)
assert refused_entry.status_code == 409 and "Declined" in refused_entry.get_json()["error"]

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
# A word after the code is left out, so a polite reply still works.
assert whatsapp.read_reply("Yes VR-40221 ok thanks") == ("decide", db.APPROVED, "VR-40221")
assert whatsapp.read_reply("no 40221 sorry") == ("decide", db.DECLINED, "VR-40221")
assert whatsapp.read_reply("IN KT 4821 now") == ("gate", db.ENTRY, "KT-4821")
assert whatsapp.read_reply("out rm-0937 done") == ("gate", db.EXIT, "RM-0937")
# A reference that does not read is still named as typed.
assert whatsapp.read_reply("YES VR 99 ok") == ("decide", db.APPROVED, "VR99OK")

print("escalation never decides, it only asks again")
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 (db.ago(1 / 24), b["reference"]))
db.forget_cache()
due = visits.due_for_escalation()
assert [v["reference"] for v in due] == [b["reference"]], due
whatsapp.notify_backup(due[0], people.approvers_for(people.approver_table(), due[0]))
visits.mark_escalated(b["reference"])
after = client.get(f"/api/visit/{b['token']}").get_json()
assert after["status"] == "escalated" and after["escalated_at"]
# Here the approver is also the backup, so the escalation reminds that one person.
assert "Reminder" in sent[-1][1]
assert templates[-1][0] == "+911234567890" and templates[-1][1][1].startswith("Reminder")
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
# No code outlives its visit, even after a failed send.
with db.connect() as conn:
    orphans = conn.execute("SELECT COUNT(*) AS n FROM gate_codes WHERE reference NOT IN"
                           " (SELECT reference FROM visits)").fetchone()["n"]
assert orphans == 0, orphans
print("  old visits, their photos and their codes deleted, today's kept")

print("the admin list")
# A guard holds the gate key. It must never open the admin list.
for path in ("/api/admin/visits", "/api/admin/summary", "/api/admin/export.csv"):
    assert client.get(path).status_code == 403, path
    assert client.get(path, headers={"X-Admin-Key": "guess"}).status_code == 403, path
    assert client.get(path, headers={"X-Admin-Key": GATE_KEY_TEXT}).status_code == 403, path
assert client.get("/admin").status_code == 200
# No ADMIN_KEY, or ADMIN_KEY equal to GATE_KEY, locks the admin page only.
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
    run = subprocess.run([sys.executable, "-c", "from core import config"], env=env,
                         capture_output=True, text=True, cwd=APP_DIR)
    return run.returncode == 0, run.stderr


# Unsafe settings stop the start, with a sentence that says what to set.
assert starts_with()[0], "the test settings start"
for changes, says in (({"ALLOW_UNSIGNED_WEBHOOK": ""}, "META_APP_SECRET"),
                      ({"GATE_KEY": "short"}, "20 characters"),
                      ({"GATE_KEY": "change-me-to-something-random"}, ".env.example"),
                      ({"APPROVERS": "{Delivery: +911}"}, "APPROVERS is not valid JSON"),
                      ({"APPROVERS": '["+911"]'}, "APPROVERS must be a JSON object")):
    started, error = starts_with(**changes)
    assert not started and says in error, (changes, error[-300:])
assert starts_with(ALLOW_UNSIGNED_WEBHOOK="", META_APP_SECRET="a-real-secret")[0]
# A key with a letter outside ASCII is a wrong key, not a server error.
assert client.get("/api/gate/board", headers={"X-Gate-Key": "clé"}).status_code == 403
assert client.get("/api/admin/summary", headers={"X-Admin-Key": "clé"}).status_code == 403
# Locked, every admin call is refused, even an empty key or the old right key.
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
        assert row["approvers"] == list(people.approvers_for(table, row))
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
# Demo values in the server settings are named for the admin. Fixed, each one goes away.
gaps = " ".join(summary["setup_gaps"])
assert "GATE_DESK_PHONE" in gaps and "STAFF_ENTRY_TEMPLATE" in gaps, gaps
assert "ADMIN_PHONE" not in gaps and "TEMPLATE_FALLBACK" not in gaps, gaps
# Here the gate desk is also the approver, as on the demo: one person approves and lets in.
assert f"{config.GUARD} can approve a visit and also let the visitor in" in gaps, gaps
real_settings = (config.GATE_DESK_PHONE, config.STAFF_ENTRY_TEMPLATE, config.ADMIN_PHONE_SET,
                 config.GUARD, config.GATE_KEY)
config.GATE_DESK_PHONE, config.STAFF_ENTRY_TEMPLATE = "+912212345678", "staff_entry"
config.ADMIN_PHONE_SET, config.GUARD = False, "+919999999990"
try:
    gaps = client.get("/api/admin/summary", headers=ADMIN).get_json()["setup_gaps"]
    assert len(gaps) == 1 and "ADMIN_PHONE is not set" in gaps[0], gaps
    config.ADMIN_PHONE_SET = True
    assert client.get("/api/admin/summary", headers=ADMIN).get_json()["setup_gaps"] == []
    # A long key of few characters is long but easy to guess: a warning, not a refusal.
    config.GATE_KEY = "x" * 20
    gaps = client.get("/api/admin/summary", headers=ADMIN).get_json()["setup_gaps"]
    assert len(gaps) == 1 and gaps[0].startswith("GATE_KEY repeats"), gaps
finally:
    (config.GATE_DESK_PHONE, config.STAFF_ENTRY_TEMPLATE, config.ADMIN_PHONE_SET,
     config.GUARD, config.GATE_KEY) = real_settings
# A download's name has the campus date, as its rows do, not the UTC date.
assert export.file_name("x", "csv") == (
    f"x-{datetime.now(config.WORK_TIMEZONE).strftime('%Y-%m-%d')}.csv")
assert [a["reason"] for a in summary["approvers"]] == [
    r for r in config.REASONS if r != config.OFFICE_REASON], "offices have their own pairs"
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

print("export of every entry and exit")
# The whole history is for the admin only. The gate has no export at all.
assert client.get("/api/export.csv", headers=KEY).status_code == 404
assert client.get("/api/admin/export.csv", headers=KEY).status_code == 403
assert client.get("/api/admin/export.csv").status_code == 403

dump = client.get("/api/admin/export.csv", headers=ADMIN)
assert dump.status_code == 200
assert "text/csv" in dump.headers["Content-Type"]
assert "attachment" in dump.headers["Content-Disposition"]




ZONE = config.WORK_TIMEZONE.key
rows = csv_rows(dump.get_data(as_text=True))
head = list(rows[0].keys())
assert head[:5] == ["Reference", "Name", "Phone", "Address", "Reason"], head
assert f"Entered ({ZONE})" in head and "Decided by" in head, head

# The visitor who went in and out must carry both times, as campus time.
done = [r for r in rows if r["Reference"] == ref2]
assert len(done) == 1, done
assert done[0]["Status"] == "Left"
stored = visits.get(ref2)
assert done[0][f"Entered ({ZONE})"] == datetime.fromisoformat(stored["entered_at"]).astimezone(
    config.WORK_TIMEZONE).strftime("%Y-%m-%d %H:%M"), done[0]
assert done[0][f"Exited ({ZONE})"], done[0]
# Guests come out readable, not as JSON. Who decided is named, not a code word.
assert done[0]["People with them"] == "Ravi Rao", done[0]
assert done[0]["Decided by"] == f"Approver {stored['decided_phone']}", done[0]["Decided by"]
# The log says when the gate photo was taken, on the web gate as on WhatsApp.
assert done[0][f"Photo taken ({ZONE})"] == done[0][f"Entered ({ZONE})"], done[0]
photographed = next(r for r in rows if r["Reference"] == code)
assert photographed[f"Photo taken ({ZONE})"] == photographed[f"Entered ({ZONE})"], photographed
# A visit that never entered has empty times rather than the word None.
never = next(r for r in rows if r["Status"] == "Declined")
assert never[f"Entered ({ZONE})"] == "" and never[f"Exited ({ZONE})"] == ""
assert "None" not in dump.get_data(as_text=True)

# The export quotes cells that spreadsheets would run as formulas.
attack = dict(payload, name="=HYPERLINK(\"https://evil.test\",\"click\")",
              address="+1+1", reason="@SUM(1:9)", visiting="-2+3")
assert client.post("/api/requests", json=attack).status_code == 201
armed = client.get("/api/admin/export.csv", headers=ADMIN).get_data(as_text=True)
row = next(r for r in csv_rows(armed) if r["Name"].endswith('click")'))
for column in ("Name", "Address", "Reason", "Visiting"):
    assert row[column].startswith("'"), (column, row[column])
# The text itself is kept, only disarmed.
assert row["Name"] == "'=HYPERLINK(\"https://evil.test\",\"click\")"
# Ordinary values are left exactly as they were.
assert not row["Reference"].startswith("'")
# A checked +number shows as text, never as 9.19E+11 or with a quote. Anything else is disarmed.
assert export.safe_cell("+919876543210") == '="+919876543210"'
assert export.safe_cell('+91"),HYPERLINK("x').startswith("'")
assert export.safe_cell("+1+1") == "'+1+1"
print("  formula cells disarmed in the export")
print(f"  {len(rows)} visits exported with entry and exit times")

print("rate limits on the public address")
limits.forget_hits()

# Creating requests is capped so a stranger cannot spam the approver's phone.
limit = config.REQUESTS_PER_HOUR
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

# No lockout: the right key works after any number of wrong ones.
for _ in range(50):
    assert client.get(f"/api/pass/{exit2}", headers=KEY).status_code == 200
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

# Callers silent for an hour are swept out past MAX_CALLERS. Recent ones stay.
limits.forget_hits()
limits.add_silent_callers(limits.MAX_CALLERS + 1, 7200)
assert client.post("/api/requests", json={**payload, "phone": "123"}).status_code == 400
assert limits.hit_buckets() == 1, limits.hit_buckets()
print(f"  {limits.MAX_CALLERS + 1} silent callers swept out, the live one kept")
limits.forget_hits()

finish()

"""End to end check with the WhatsApp call stubbed out.

Run it with: .venv\\Scripts\\python.exe test_app.py
It sends no WhatsApp messages and uses a throwaway database.
"""

import os
import tempfile

os.environ.update(
    META_TOKEN="test-token",
    META_PHONE_NUMBER_ID="100000000000000",
    META_VERIFY_TOKEN="visitor-access-verify",
    META_APP_SECRET="",
    MAIN_APPROVER="+911234567890",
    BACKUP_APPROVER="+911234567890",
    GUARD="+911234567890",
    GATE_KEY="test-gate-key",
    GATE_DESK_PHONE="+912200000000",
    ESCALATE_MINUTES="30",
    RETAIN_DAYS="1",
    DATABASE_PATH=os.path.join(tempfile.mkdtemp(), "test.db"),
)

import app as application
import db
import whatsapp

sent = []
whatsapp.send = lambda to, body: sent.append((to, body))

db.init()
client = application.app.test_client()
KEY = {"X-Gate-Key": "test-gate-key"}

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

print("gate over whatsapp")
# A bare code is a lookup.
looked = say(APPROVER, code)
assert "Approved" in looked and "Asha Rao" in looked
assert say(APPROVER, code.lower().replace("vr-", "")) .count("Asha Rao") == 1

# OUT before IN is refused.
assert "Not checked in" in say(APPROVER, f"OUT {code}")
# A photo with no IN before it lets nobody in.
assert "No entry is waiting" in snap(APPROVER)
# IN only asks for the photo, and names the person to photograph.
asked = say(APPROVER, f"IN {code}")
assert "Take a photo of Asha Rao" in asked and code in asked, asked
assert client.get(f"/api/visit/{token}").get_json()["status"] == "approved"
# The photo lets them in.
assert "Inside now" in snap(APPROVER)
entered = client.get(f"/api/visit/{token}").get_json()
assert entered["status"] == "inside" and entered["entered_at"]
assert db.photo_of(code)["taken_at"] == entered["entered_at"]
# A second photo on the same IN lets nobody else in, and a second IN is refused.
assert "No entry is waiting" in snap(APPROVER)
assert "Already inside" in say(APPROVER, f"IN {code}")
# OUT closes it, and then the code is dead.
assert "Closed" in say(APPROVER, f"OUT {code}")
assert client.get(f"/api/visit/{token}").get_json()["status"] == "closed"
assert "closed" in say(APPROVER, f"IN {code}").lower()
assert "No pass has code VR-9999" in say(APPROVER, "IN VR-9999")
assert "Add the code" in say(APPROVER, "IN")
print("  lookup, entry, exit and decommission all correct")

print("the gate photo")


def approved():
    made = new_request()
    say(APPROVER, f"YES {made['reference']}")
    return made


def status_of(made):
    return client.get(f"/api/visit/{made['token']}").get_json()["status"]


# Two INs in a row: the photo goes to the second, and the reply says which.
first, second_in = approved(), approved()
say(APPROVER, f"IN {first['reference']}")
say(APPROVER, f"IN {second_in['reference']}")
went_in = snap(APPROVER)
assert second_in["reference"] in went_in and "Inside now" in went_in, went_in
assert status_of(first) == "approved" and status_of(second_in) == "inside"

# An IN older than the time limit is dead. The photo must not let anyone in.
say(APPROVER, f"IN {first['reference']}")
with db.connect() as conn:
    conn.execute("UPDATE photo_waits SET asked = ?", ("2020-01-01T00:00:00+00:00",))
late = snap(APPROVER)
assert "No entry is waiting" in late and str(application.PHOTO_MINUTES) in late, late
assert status_of(first) == "approved"

# The web gate let the visitor in while the guard was taking the photo.
say(APPROVER, f"IN {first['reference']}")
client.post(f"/api/pass/{first['reference']}/entry", headers=KEY)
assert "Already inside" in snap(APPROVER)
assert db.photo_of(first["reference"]) is None

# A photo from a stranger gets no answer and changes nothing.
third = approved()
say(APPROVER, f"IN {third['reference']}")
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
ref2 = second["reference"]
assert client.get(f"/api/pass/{ref2}", headers=KEY).status_code == 200
assert client.get(f"/api/pass/{ref2.lower()}", headers=KEY).status_code == 200
assert client.post(f"/api/pass/{ref2}/exit", headers=KEY).status_code == 409
entered = client.post(f"/api/pass/{ref2}/entry", headers=KEY)
assert entered.status_code == 200 and entered.get_json()["status"] == "inside"
assert client.post(f"/api/pass/{ref2}/entry", headers=KEY).status_code == 409
left = client.post(f"/api/pass/{ref2}/exit", headers=KEY)
assert left.status_code == 200 and left.get_json()["status"] == "closed"
for action in ("entry", "exit"):
    dead = client.post(f"/api/pass/{ref2}/{action}", headers=KEY)
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
refused_body = client.post(f"/api/pass/{ref2}/entry", headers=KEY).get_json()
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
assert client.post(f"/api/pass/{ref2}/sideways", headers=KEY).status_code == 404
assert client.post("/api/pass/VR-9999/entry", headers=KEY).status_code == 404
assert client.get(f"/api/pass/{ref2}", headers={"X-Gate-Key": "wrong"}).status_code == 403

print("a declined pass never opens the gate")
bad = new_request()
say(APPROVER, f"NO {bad['reference']}")
refused = client.post(f"/api/pass/{bad['reference']}/entry", headers=KEY)
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
    conn.execute("UPDATE visits SET created_at = ? WHERE reference = ?",
                 ("2020-01-01T00:00:00+00:00", b["reference"]))
due = db.due_for_escalation()
assert [v["reference"] for v in due] == [b["reference"]], due
whatsapp.notify_backup(due[0])
db.mark_escalated(b["reference"])
after = client.get(f"/api/visit/{b['token']}").get_json()
assert after["status"] == "escalated" and after["escalated_at"]
assert "Backup approver" in sent[-1][1]
# An escalated request is still undecided, and a visitor inside never escalates.
assert b["reference"] in [v["reference"] for v in db.open_requests()]
assert ref2 not in [v["reference"] for v in db.open_requests()]
assert ref2 not in [v["reference"] for v in db.due_for_escalation()]

print("retention deletes records older than RETAIN_DAYS")
old = new_request()
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = ? WHERE reference = ?",
                 ("2020-01-01T00:00:00+00:00", old["reference"]))
assert db.purge_old() >= 1
assert db.get(old["reference"]) is None
assert client.get(f"/api/visit/{old['token']}").status_code == 404
# Today's records survive the purge.
assert db.get(a["reference"]) is not None

print("pages are served")
for path in ("/", "/app.js", "/gate", "/gate.js"):
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

print()
print("all checks passed")

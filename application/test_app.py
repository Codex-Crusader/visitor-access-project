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
# IN works, then a second IN is refused.
assert "Inside now" in say(APPROVER, f"IN {code}")
assert client.get(f"/api/visit/{token}").get_json()["entered_at"]
assert "Already inside" in say(APPROVER, f"IN {code}")
# OUT closes it, then the code is dead.
assert "Closed" in say(APPROVER, f"OUT {code}")
assert client.get(f"/api/visit/{token}").get_json()["status"] == "closed"
assert "closed" in say(APPROVER, f"IN {code}").lower()
assert "No pass has code VR-9999" in say(APPROVER, "IN VR-9999")
assert "Add the code" in say(APPROVER, "IN")
print("  lookup, entry, exit and decommission all correct")

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

print("retention actually deletes, as the privacy screen promises")
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

print()
print("all checks passed")

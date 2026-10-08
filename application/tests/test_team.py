"""Gate photos, guards, offices, admins, the allow list, tags and access rules.

Run: .venv\\Scripts\\python.exe tests\\test_team.py"""

import base64
import contextlib
import io
import re
import zipfile
from PIL import Image
from datetime import datetime

# The kit comes first: it sets the settings and a clean database before the app loads.
from kit import (
    ADMIN, ADMIN_KEY_TEXT, APPROVER, GATE_KEY_TEXT, KEY, PHOTO, STRANGER, add_admin,
    add_black, add_staff, approved, as_photo, client, csv_rows, entry_of, exit_of,
    finish, inbound, is_clean_photo, jpeg, made_hours_ago, new_request, payload, say,
    sent, snap, status_of, templates,
)
import app as application
from routes import access
from routes import gate
from models import blacklist
from core import checks
from core import config
from core import db
from models import entries
from services import export
from core import limits
from models import people
from models import staff
from models import tags
from services import timer
from models import visits
from services import whatsapp

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

print("the gate desk hears about an approval, never with a gate code; added guards do not")
# Here the desk has its own number. In the kit it is the approver's, who is never told twice.
DESK = "+919811100099"
real_desk, config.GUARD = config.GUARD, DESK
try:
    sent.clear()
    told = new_request()
    assert "is now approved" in say(APPROVER, f"YES {told['reference']}"), "the reply stays last"
    to_desk = [body for to, body in sent if whatsapp.same_number(to, DESK)]
    assert len(to_desk) == 1 and told["reference"] in to_desk[0], to_desk
    assert not any(code in to_desk[0] for code in visits.codes_of(told["reference"]).values())
    assert not any(whatsapp.same_number(to, RAVI) for to, _ in sent), "one message, not one a guard"
    to_approver = [body for to, body in sent if whatsapp.same_number(to, APPROVER)]
    assert not any("Approved visitor" in body for body in to_approver), "the approver is not told"
    sent.clear()
    say(APPROVER, f"NO {new_request()['reference']}")
    assert not any(whatsapp.same_number(to, DESK) for to, _ in sent), "a decline tells no one"
    sent.clear()
    auto = new_request()
    with db.connect() as conn:
        conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                     ("2020-01-01T00:00:00+00:00", auto["reference"]))
    db.forget_cache()
    timer.auto_approve_due()
    assert [to for to, body in sent if auto["reference"] in body and "Approved visitor" in body] \
        == [DESK], sent
finally:
    config.GUARD = real_desk
# The desk that approves a request is not told again: it decided it.
sent.clear()
say(APPROVER, f"YES {new_request()['reference']}")
assert not any("Approved visitor" in body for _, body in sent), "the desk approved it itself"
print("  the desk told once on approval and automatic approval, no guard, no decline, no code")

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

print("an office has its own two approvers, and the visitor picks it from a list")
limits.forget_hits()
OFFICE_MAIN, OFFICE_BACKUP = "+919700000001", "+919700000002"
ACCOUNTS = {"name": "Accounts", "main": OFFICE_MAIN, "backup": OFFICE_BACKUP}


def add_office(body, with_key=None):
    return client.post("/api/admin/offices", json=body, headers=with_key or ADMIN)


assert add_office(ACCOUNTS, with_key=KEY).status_code == 403, "the gate key adds no office"
bad = add_office({"name": "", "main": "1", "backup": "1"})
assert bad.status_code == 400 and set(bad.get_json()["fields"]) == {"name", "main", "backup"}
single = add_office({"name": "Single desk", "main": OFFICE_MAIN, "backup": ""})
assert single.status_code == 200, single.get_json()
assert [(o["main"], o["backup"]) for o in single.get_json()["offices"]
        if o["name"] == "Single desk"] == [(OFFICE_MAIN, OFFICE_MAIN)], "one person, both roles"
client.post("/api/admin/offices/remove", json={"name": "Single desk"}, headers=ADMIN)
same = add_office({**ACCOUNTS, "backup": OFFICE_MAIN})
assert "Leave the backup empty" in same.get_json()["fields"]["backup"], same.get_json()
made = add_office(ACCOUNTS)
listed_offices = [{k: o[k] for k in ACCOUNTS} for o in made.get_json()["offices"]]
assert made.status_code == 200 and listed_offices == [ACCOUNTS], made.get_json()
assert made.get_json()["offices"][0]["tag"] == "", "no tag given, no tag kept"
assert add_office({**ACCOUNTS, "name": "accounts"}).status_code == 400, "one name, in any case"
shown = client.get("/api/config").get_json()
assert shown["offices"] == ["Accounts"] and OFFICE_MAIN not in str(shown), "names only"

office_visit = {**payload, "reason": config.OFFICE_REASON, "visiting": "x", "office": "accounts"}
assert client.post("/api/requests", json={**office_visit, "office": "Canteen"}).status_code == 400
assert client.post("/api/requests", json={**office_visit, "office": ""}).status_code == 400
to_office = client.post("/api/requests", json=office_visit).get_json()
assert to_office["office"] == "Accounts" and to_office["visiting"] == "Accounts", to_office
assert templates[-1][0] == OFFICE_MAIN, templates[-1]
assert "Accounts" in templates[-1][1], "the approver reads which office"
# Only the office's own approvers decide. They approve no reason, and still reach the app.
assert "another approver" in say(APPROVER, f"YES {to_office['reference']}")
assert "is now approved" in say(OFFICE_MAIN[1:], f"YES {to_office['reference']}")
assert visits.get(to_office["reference"])["decided_phone"] == OFFICE_MAIN
assert "another approver" in say(OFFICE_MAIN[1:], f"YES {new_request()['reference']}")
# Escalation goes to the office's backup. The admin list names the office's pair.
late_office = client.post("/api/requests", json=office_visit).get_json()
made_hours_ago(late_office, 1)
timer.escalate_due()
assert templates[-1][0] == OFFICE_BACKUP, templates[-1]
row = client.get(f"/api/admin/visits?q={late_office['reference']}", headers=ADMIN).get_json()
assert row["visits"][0]["approvers"] == [OFFICE_MAIN, OFFICE_BACKUP], row
assert row["visits"][0]["office"] == "Accounts"
assert "office" in client.get("/api/admin/export.csv", headers=ADMIN).get_data(as_text=True)
# A deleted office stops at once. Its open request goes to the reason's approvers.
removed = client.post("/api/admin/offices/remove", json={"name": "Accounts"}, headers=ADMIN)
assert removed.status_code == 200 and removed.get_json()["offices"] == []
say(OFFICE_BACKUP[1:], f"YES {late_office['reference']}")
assert visits.get(late_office["reference"])["status"] == "escalated", "the old office cannot decide"
assert "is now approved" in say(APPROVER, f"YES {late_office['reference']}")
assert client.post("/api/admin/offices/remove", json={"name": "Accounts"},
                   headers=ADMIN).status_code == 404
# With no offices, the reason works as before, with the place typed in.
typed = client.post("/api/requests", json={**payload, "reason": config.OFFICE_REASON,
                                           "visiting": "Library"})
assert typed.status_code == 201 and typed.get_json()["office"] is None, typed.get_json()
print("  routing, deciding, escalation and the fallback after a delete all follow the office")

print("more admins, each with their own key, and none of them a guard")
MEERA_PHONE, SUNIL_PHONE = "+919600000001", "+919600000002"




assert add_admin("Meera", MEERA_PHONE, with_key=KEY).status_code == 403
assert add_admin("Main", config.ADMIN_PHONE).status_code == 400, "the main admin is one already"
assert add_admin("Desk", config.GUARD).status_code == 400, "a guard must not get the admin key"
summary = client.get("/api/admin/summary", headers=ADMIN).get_json()
assert summary["you"] == access.MAIN_ADMIN and summary["main_admin"] == config.ADMIN_PHONE
added = add_admin("Meera", MEERA_PHONE)
assert added.status_code == 200, added.get_json()
MEERA = {"X-Admin-Key": added.get_json()["key"]}
summary = client.get("/api/admin/summary", headers=MEERA).get_json()
assert summary["you"] == f"Meera {MEERA_PHONE}", summary["you"]
assert [a["phone"] for a in summary["admins"]] == [MEERA_PHONE] and "key_hash" not in str(summary)
assert add_admin("Meera again", MEERA_PHONE).status_code == 400
assert client.post("/api/admin/guards", json={"name": "Meera", "phone": MEERA_PHONE},
                   headers=ADMIN).status_code == 400, "an admin's number is no guard"
assert client.post("/api/admin/guards", json={"name": "Sunil", "phone": SUNIL_PHONE},
                   headers=MEERA).status_code == 200, "an added admin adds guards"
assert add_admin("Sunil", SUNIL_PHONE).status_code == 400, "a guard's number is no admin"
assert client.get("/api/admin/summary",
                  headers={"X-Admin-Key": GATE_KEY_TEXT}).status_code == 403
assert client.post("/api/admin/admins/remove", json={"phone": MEERA_PHONE},
                   headers=MEERA).status_code == 409, "nobody deletes themselves"
# KEY on WhatsApp gives an added admin a new key of their own.
key_reply = say(MEERA_PHONE[1:], "KEY")
assert "admin key" in key_reply and ADMIN_KEY_TEXT not in key_reply, key_reply
MEERA2 = {"X-Admin-Key": key_reply.split("\n")[1]}
assert client.get("/api/admin/summary", headers=MEERA).status_code == 403, "the old key stops"
assert client.get("/api/admin/summary", headers=MEERA2).status_code == 200
gone = client.post("/api/admin/admins/remove", json={"phone": MEERA_PHONE}, headers=ADMIN)
assert gone.status_code == 200 and gone.get_json()["admins"] == []
assert client.get("/api/admin/summary", headers=MEERA2).status_code == 403
client.post("/api/admin/guards/remove", json={"phone": SUNIL_PHONE}, headers=ADMIN)
print("  own key, KEY renews it, no guard overlap, no self-delete, delete stops it")

print("staff enter with their 7-digit code, and the log names the guard")
DEV_PHONE = "+919500000001"




assert add_staff("Dr Dev", DEV_PHONE, with_key=KEY).status_code == 403
bad = add_staff("", "12")
assert bad.status_code == 400 and set(bad.get_json()["fields"]) == {"name", "phone"}
made = add_staff("Dr Dev", DEV_PHONE).get_json()
dev_code = made["code"]
assert re.fullmatch(r"[1-9]\d{6}", dev_code), dev_code
assert [p["code"] for p in made["staff"]] == [dev_code]
again = add_staff("Dev again", DEV_PHONE)
assert again.status_code == 400, (again.status_code, again.get_data(as_text=True))
assert whatsapp.read_reply(dev_code) == ("staff", None, dev_code)
assert whatsapp.read_reply(f"in {dev_code[:3]} {dev_code[3:]}") == ("staff", "entry", dev_code)
assert whatsapp.read_reply(f"OUT {dev_code}") == ("staff", "exit", dev_code)
assert whatsapp.read_reply("40221")[0] == "lookup", "a reference is still a reference"

sent.clear()
client.post("/webhook/whatsapp", json=inbound(STRANGER, dev_code))
assert not sent and not staff.recent_entries(), "a stranger's code records nothing"
entry_reply = say(APPROVER, dev_code)
assert entry_reply.startswith("Entry recorded: Dr Dev"), entry_reply
assert "message about this entry was sent" in entry_reply, entry_reply
to_dev = [body for to, body in sent if to == DEV_PHONE]
assert len(to_dev) == 1 and "Campus entry recorded for Dr Dev" in to_dev[0], to_dev
assert to_dev[0].count("+91") == 0 and "by Gate desk." in to_dev[0], "no guard's number to staff"
assert staff.recent_entries()[0]["entered_by"] == f"Gate desk {config.GUARD}"
# A second send of the same code within 2 minutes records and sends nothing more.
again_reply = say(APPROVER, f"IN {dev_code[:3]} {dev_code[3:]}")
assert again_reply.startswith("Already recorded: Dr Dev"), again_reply
assert len([to for to, _ in sent if to == DEV_PHONE]) == 1 and len(staff.recent_entries()) == 1


def later():
    """Moves every allow list entry 3 minutes back, past the repeat window."""
    with db.connect() as writer:
        writer.execute("UPDATE staff_entries SET entered_at = %s", (db.ago(3 / 1440),))
    db.forget_cache()


later()
assert say(APPROVER, f"IN {dev_code[:3]} {dev_code[3:]}").startswith("Entry recorded")
later()
unknown_code = "1000000" if dev_code != "1000000" else "1000001"
assert "No one on the allow list" in say(APPROVER, unknown_code)

# The gate page sees the name, never the number, and records who let them in.
assert client.get(f"/api/staff/{dev_code}").status_code == 403
seen = client.get(f"/api/staff/{dev_code}", headers=KEY).get_json()
assert seen == {"code": dev_code, "name": "Dr Dev", "tag": "", "blacklisted": False}, seen
assert client.get(f"/api/staff/{unknown_code}", headers=KEY).status_code == 404
by_page = client.post(f"/api/staff/{dev_code}/in", headers=KEY)
assert by_page.status_code == 200 and DEV_PHONE not in by_page.get_data(as_text=True)
assert by_page.get_json()["new"] is True and by_page.get_json()["told"] is True
assert staff.recent_entries()[0]["entered_by"] == access.DESK_KEY
double = client.post(f"/api/staff/{dev_code}/in", headers=KEY).get_json()
assert double["new"] is False and double["at"] == by_page.get_json()["at"]
later()
# With a template set, the message goes as that template. A failed message keeps the entry.
config.STAFF_ENTRY_TEMPLATE = "staff_entry"
try:
    client.post(f"/api/staff/{dev_code}/in", headers=KEY)
    assert templates[-1][0] == DEV_PHONE and templates[-1][1][0] == "Dr Dev", templates[-1]
finally:
    config.STAFF_ENTRY_TEMPLATE = ""
later()
real_send = whatsapp.send


def fails_for_dev(to, body):
    """Meta refuses the message to the staff member. The guard's reply still goes out."""
    if to == DEV_PHONE:
        broken()
    real_send(to, body)


whatsapp.send = fails_for_dev
try:
    before = len(staff.recent_entries())
    failed_send = client.post(f"/api/staff/{dev_code}/in", headers=KEY)
    assert failed_send.status_code == 200 and failed_send.get_json()["told"] is False
    assert len(staff.recent_entries()) == before + 1
    later()
    assert "could not be sent" in say(APPROVER, f"IN {dev_code}"), "the guard is told the truth"
finally:
    whatsapp.send = real_send
later()

# A scan is a toggle: an entry, then an exit after an entry today. A double tap repeats.
EVE_PHONE = "+919500000003"
eve_code = add_staff("Eve", EVE_PHONE).get_json()["code"]


def eve_moves():
    return [e["kind"] for e in staff.recent_entries() if e["code"] == eve_code]


def eve_today():
    """Eve's row in the Today list, or {} when she is not in it."""
    return next((p for p in staff.today() if p["code"] == eve_code), {})


assert eve_today() == {}
sent.clear()
# A scan clears only the reads it changes: the next scan still finds the allow list in memory.
def cached_lists():
    # noinspection PyProtectedMember
    return {key[:2] for key in db._cache}


staff.by_code(eve_code)
assert {("models.staff", "_by_code"), ("models.staff", "today")} <= cached_lists()
assert say(APPROVER, eve_code).startswith("Entry recorded: Eve")
assert ("models.staff", "_by_code") in cached_lists(), "the allow list stays in memory"
assert ("models.staff", "today") not in cached_lists(), "today's list is read again"
assert say(APPROVER, eve_code).startswith("Already recorded: Eve entered"), "a double tap"
assert eve_moves() == ["entry"] and eve_today()["last_kind"] == "entry"
later()
left = say(APPROVER, eve_code)
assert left.startswith("Exit recorded: Eve"), left
assert [to for to, _ in sent].count(EVE_PHONE) == 1, "no message to the person on exit"
assert say(APPROVER, eve_code).startswith("Already recorded: Eve left"), "a double tap"
assert eve_moves() == ["exit", "entry"]
assert eve_today()["last_kind"] == "exit" and eve_today()["first_in"], eve_today()
later()
# The gate page sends scan, and reads which one it was.
back = client.post(f"/api/staff/{eve_code}/scan", headers=KEY).get_json()
assert back["kind"] == "entry" and back["new"] is True and back["told"] is True, back
later()
out = client.post(f"/api/staff/{eve_code}/scan", headers=KEY).get_json()
assert out["kind"] == "exit" and out["new"] is True and EVE_PHONE not in str(out), out
assert client.post(f"/api/staff/{eve_code}/sideways", headers=KEY).status_code == 404
later()
# IN and OUT say which one, to correct a wrong scan. OUT twice is one exit.
assert say(APPROVER, f"OUT {eve_code}").startswith("Exit recorded: Eve")
assert say(APPROVER, f"OUT {eve_code}").startswith("Already recorded: Eve left")
summary_today = client.get("/api/admin/summary", headers=ADMIN).get_json()["staff_today"]
assert [p["last_kind"] for p in summary_today if p["code"] == eve_code] == ["exit"]
assert "phone" not in summary_today[0], "the Today list needs no number"
# After 16 hours a scan starts again: yesterday's entry with no exit does not turn a scan
# into an exit, and it is not in the Today list.
with db.connect() as conn:
    conn.execute("DELETE FROM staff_entries WHERE code = %s", (eve_code,))
    conn.execute("INSERT INTO staff_entries (code, name, phone, entered_at, entered_by)"
                 " VALUES (%s, 'Eve', %s, %s, 'test')", (eve_code, EVE_PHONE, db.ago(1)))
db.forget_cache()
assert staff.recent_entries()[0]["kind"] == "entry", "a row with no kind is an entry"
assert eve_today() == {}
assert say(APPROVER, eve_code).startswith("Entry recorded: Eve"), "a new day starts with an entry"
# A night shift: the entry 8 hours ago, before midnight or not, makes this scan the exit.
with db.connect() as conn:
    conn.execute("DELETE FROM staff_entries WHERE code = %s", (eve_code,))
    conn.execute("INSERT INTO staff_entries (code, name, phone, entered_at, entered_by)"
                 " VALUES (%s, 'Eve', %s, %s, 'test')", (eve_code, EVE_PHONE, db.ago(8 / 24)))
db.forget_cache()
assert eve_today()["last_kind"] == "entry", "still in from the night shift: on campus"
assert say(APPROVER, eve_code).startswith("Exit recorded: Eve"), "the night shift ends"
# A wrong scan changed within 10 minutes: the same row, the other kind, nothing added.
with db.connect() as conn:
    conn.execute("DELETE FROM staff_entries WHERE code = %s", (eve_code,))
db.forget_cache()
assert client.post(f"/api/staff/{eve_code}/scan", headers=KEY).get_json()["kind"] == "entry"
changed = client.post(f"/api/staff/{eve_code}/out", headers=KEY).get_json()
assert changed["kind"] == "exit" and changed["new"] is True and eve_moves() == ["exit"], changed
assert say(APPROVER, f"IN {eve_code}").startswith("Entry recorded: Eve")
assert eve_moves() == ["entry"], "changed back, still one row"
# A gate page opened before the toggle records every code as an entry, so it must reload.
old_page = client.post(f"/api/staff/{eve_code}/entry", headers=KEY)
assert old_page.status_code == 409 and "Reload" in old_page.get_json()["error"]
assert eve_moves() == ["entry"]
# A stolen gate key cannot try every code: scans share the 60 a minute of reads.
limits.forget_hits()
for guess in range(gate.CODES_PER_MINUTE):
    client.post(f"/api/staff/{9000000 + guess}/scan", headers=KEY)
assert client.post(f"/api/staff/{eve_code}/scan", headers=KEY).status_code == 429
assert eve_moves() == ["entry"], "a refused scan records nothing"
limits.forget_hits()
# A blacklisted number cannot enter by a scan, but can leave.
later()
add_black(EVE_PHONE, "Eve")
assert client.post(f"/api/staff/{eve_code}/scan", headers=KEY).get_json()["kind"] == "exit"
later()
refused = client.post(f"/api/staff/{eve_code}/scan", headers=KEY)
assert refused.status_code == 409 and refused.get_json()["kind"] == "entry", refused.get_json()
assert "blacklist" in say(APPROVER, eve_code)
assert eve_moves()[0] == "exit", "the refused entry is not recorded"
client.post("/api/admin/blacklist/remove", json={"phone": EVE_PHONE}, headers=ADMIN)

# The staff log has one row per visit: each entry with the exit after it on the same day.
YESTERDAY = db.ago(1)
day_rows = staff.pair_visits([
    {"code": "1", "name": "A", "phone": "+91", "entered_at": YESTERDAY, "entered_by": "g",
     "kind": "entry"},
    {"code": "2", "name": "B", "phone": "+91", "entered_at": YESTERDAY, "entered_by": "g",
     "kind": "exit"},
    {"code": "1", "name": "A", "phone": "+91", "entered_at": db.now(), "entered_by": "g",
     "kind": "entry"},
])
cells = {(row["name"], export.local(row["in"] or row["out"], "%Y-%m-%d")):
         [export.read(row, how) for _, how in export.ALLOW_COLUMNS] for row in day_rows}
yesterday, today_date = export.local(YESTERDAY, "%Y-%m-%d"), export.local(db.now(), "%Y-%m-%d")
assert len(day_rows) == 3, day_rows
assert cells["A", yesterday][6] == export.NO_EXIT, "yesterday's entry with no exit"
assert cells["B", yesterday][4] == export.NO_ENTRY, "an exit with no entry"
assert cells["A", today_date][6] == export.STILL_INSIDE, "today, still inside"
later()
summary_answer = client.get("/api/admin/summary", headers=ADMIN)
summary = summary_answer.get_json()
# The page asks every minute: an unchanged summary is an empty 304, a scan changes it.
tag = summary_answer.headers["ETag"]
again = client.get("/api/admin/summary", headers={**ADMIN, "If-None-Match": tag})
assert again.status_code == 304 and not again.get_data(), again.status_code
assert summary_answer.headers["Cache-Control"] == "no-store"
client.post(f"/api/staff/{dev_code}/scan", headers=KEY)
assert client.get("/api/admin/summary",
                  headers={**ADMIN, "If-None-Match": tag}).status_code == 200, "a scan is news"
later()
assert access.DESK_KEY in [e["entered_by"] for e in summary["staff_entries"]]
# The staff entry log is its own file, for the admin only. It holds every entry with its
# guard, the date in its own column, and disarms a name that looks like a formula.
sneaky_code = add_staff("=HYPERLINK(1)", "+919500000002").get_json()["code"]
say(APPROVER, sneaky_code)
for wrong in ({}, KEY):
    assert client.get("/api/admin/staff-entries.csv", headers=wrong).status_code == 403
staff_log = client.get("/api/admin/staff-entries.csv", headers=ADMIN)
assert staff_log.headers["Cache-Control"] == "no-store"
assert 'filename="staff-entries-' in staff_log.headers["Content-Disposition"]
allow_csv = staff_log.get_data(as_text=True)
allow_rows = csv_rows(allow_csv)
assert list(allow_rows[0]) == [heading for heading, _ in export.ALLOW_COLUMNS], allow_rows[0]
today = datetime.now(config.WORK_TIMEZONE).strftime("%Y-%m-%d")
assert allow_rows[-1][f"Date ({export.ZONE})"] == today, allow_rows[-1]
assert re.fullmatch(r"\d\d:\d\d", allow_rows[-1][f"Entry time ({export.ZONE})"]), allow_rows[-1]
eve_rows = [r for r in allow_rows if r["Allow list code"] == eve_code]
assert eve_rows and all(re.fullmatch(r"\d\d:\d\d", r[f"Exit time ({export.ZONE})"])
                        or r[f"Exit time ({export.ZONE})"] in (export.NO_EXIT, export.STILL_INSIDE)
                        for r in eve_rows), eve_rows
assert "allow-list-entries.csv" not in zipfile.ZipFile(io.BytesIO(
    client.get("/api/admin/export.zip", headers=ADMIN).get_data())).namelist(), "a separate log"
assert len(allow_rows) == len(staff.all_visits()) > 3, "every visit, not the last 100"
assert '="+919500000001"' in [r["WhatsApp number"] for r in allow_rows], "shown as text"
assert f"Gate desk {config.GUARD}" in allow_csv and access.DESK_KEY in allow_csv
assert "'=HYPERLINK(1)" in allow_csv, "a formula name gets a quote in front"
client.post("/api/admin/staff/remove", json={"code": sneaky_code}, headers=ADMIN)
client.post("/api/admin/staff/remove", json={"code": eve_code}, headers=ADMIN)
# A sleeping database leaves the visitor page its settings, with no office list.
real_names = people.office_names
people.office_names = broken
try:
    with contextlib.redirect_stderr(io.StringIO()):
        shown = client.get("/api/config")
    assert shown.status_code == 200 and shown.get_json()["offices"] == [], shown.get_json()
finally:
    people.office_names = real_names
assert summary["staff"][0]["code"] == dev_code

# Deleted, the code stops at once. The entries stay until the retention period ends.
gone = client.post("/api/admin/staff/remove", json={"code": dev_code}, headers=ADMIN)
assert gone.status_code == 200 and gone.get_json()["staff"] == []
assert "No one on the allow list" in say(APPROVER, dev_code)
assert staff.recent_entries(), "the log keeps the entries"
with db.connect() as conn:
    conn.execute("UPDATE staff_entries SET entered_at = %s", (db.ago(2),))
db.forget_cache()
visits.purge_old()
assert not staff.recent_entries(), "old staff entries are deleted"
print("  a guard's code records at once, staff told, the page sees no number, delete stops it")

print("the ZIP holds the log, a file for each gate page photo, and streams")
limits.forget_hits()
assert client.get("/api/admin/export.zip", headers=KEY).status_code == 403
shot = approved()
assert client.post(f"/api/pass/{entry_of(shot)}/entry", headers=KEY, json=PHOTO).status_code == 200
by_phone_photo = approved()
say(APPROVER, f"IN {entry_of(by_phone_photo)}")
snap(APPROVER)
# A name that a spreadsheet would run as a formula, so the page must show it as text.
attack = dict(payload, name="=HYPERLINK(\"https://evil.test\",\"click\")")
assert client.post("/api/requests", json=attack).status_code == 201
download = client.get("/api/admin/export.zip", headers=ADMIN)
assert download.headers["Content-Type"] == "application/zip"
assert "visit-log-" in download.headers["Content-Disposition"]
assert download.headers["Cache-Control"] == "no-store"
assert download.is_streamed, "the ZIP streams, so photos never sit in memory together"
archive = zipfile.ZipFile(io.BytesIO(download.get_data()))
assert archive.testzip() is None, "every file in the ZIP reads back whole"
log_rows = {row["Reference"]: row for row in csv_rows(archive.read("visits.csv").decode())}
photo_name = log_rows[shot["reference"]]["Photo file"]
assert photo_name == f"photos/{shot['reference']}.jpg", photo_name
assert is_clean_photo(archive.read(photo_name)), "the stored, cleaned JPEG"
# The text is compressed for a weak signal. A JPEG is stored as it is: it does not shrink.
kinds = {info.filename: info.compress_type for info in archive.infolist()}
assert kinds["visits.html"] == kinds["visits.csv"] == zipfile.ZIP_DEFLATED, kinds
assert kinds[photo_name] == zipfile.ZIP_STORED, kinds
assert log_rows[by_phone_photo["reference"]]["Photo file"] == "", "a WhatsApp photo is not stored"
# The page shows each visit beside its photo, and escapes every value.
page = archive.read("visits.html").decode()
assert f'src="{photo_name}"' in page and shot["reference"] in page
assert "Photo in the guard's WhatsApp chat" in page
assert "=HYPERLINK(&quot;https://evil.test&quot;" in page and "<script" not in page
assert "visits.html" in archive.read("README.txt").decode()
stored = [n for n in archive.namelist() if n.startswith("photos/")]
with db.connect() as conn:
    kept = conn.execute("SELECT COUNT(*) AS n FROM photos WHERE image IS NOT NULL").fetchone()["n"]
assert len(stored) == kept, (len(stored), kept)
# Photos come in batches of 50 by reference: none twice, none missed.
real_batch = entries.PHOTO_BATCH
entries.PHOTO_BATCH = 2
try:
    batched = [reference for reference, _ in entries.stored_photos()]
finally:
    entries.PHOTO_BATCH = real_batch
assert batched == sorted(set(batched)) and len(batched) == kept, batched
print(f"  {kept} photos, each named in visits.csv, a WhatsApp photo left empty")

print("worst cases: a ban while a request waits, an old office list, who changed what")
limits.forget_hits()
# A ban while requests wait: they are declined at once, and nothing approves them later.
waiting_a, waiting_b = new_request(), new_request()
already_ok = approved()
with db.connect() as conn:
    conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", waiting_b["reference"]))
banned_now = add_black("+91 98765 43210").get_json()
assert set(banned_now["declined"]) >= {waiting_a["reference"], waiting_b["reference"]}
assert already_ok["reference"] not in banned_now["declined"], "an approved pass stays approved"
assert visits.get(waiting_a["reference"])["status"] == "declined"
assert visits.get(waiting_a["reference"])["decided_by"] == db.BY_BLACKLIST
timer.auto_approve_due()
assert visits.get(waiting_b["reference"])["status"] == "declined", "the timer approves nothing"
# A YES racing the ban: the request is still open, but the approval statement refuses it.
with db.connect() as conn:
    conn.execute("DELETE FROM blacklist")
db.forget_cache()
racing = new_request()
with db.connect() as conn:
    conn.execute("INSERT INTO blacklist (number_key, phone_key, phone, name, reason, added_at)"
                 " VALUES ('919876543210', '9876543210', '+91 98765 43210', 'Kiran', '', %s)",
                 (db.now(),))
db.forget_cache()
assert "on the blacklist" in say(APPROVER, f"YES {racing['reference']}")
assert visits.get(racing["reference"])["status"] == "pending"
assert visits.decide(racing["reference"], db.DECLINED, db.BY_MAIN) is not None, "NO still works"
# The gate board marks a banned visitor, and never sends the phone.
board_now = client.get("/api/gate/board", headers=KEY).get_json()
marked = [v for v in board_now["expected"] if v["reference"] == already_ok["reference"]]
assert marked and marked[0]["blacklisted"] is True and "phone" not in marked[0], marked
client.post("/api/admin/blacklist/remove", json={"phone": "9876543210"}, headers=ADMIN)

# An office deleted after the page loaded: the answer carries the list as it is now.
add_office(ACCOUNTS)
add_office({**ACCOUNTS, "name": "Library"})
client.post("/api/admin/offices/remove", json={"name": "Accounts"}, headers=ADMIN)
stale = client.post("/api/requests", json={**office_visit, "office": "Accounts"})
assert stale.status_code == 400 and stale.get_json()["offices"] == ["Library"], stale.get_json()
assert "not on the list now" in stale.get_json()["error"]
client.post("/api/admin/offices/remove", json={"name": "Library"}, headers=ADMIN)

# Every admin change is logged under the admin who made it, and never holds a key.
with db.connect() as conn:
    conn.execute("DELETE FROM admin_changes")
db.forget_cache()
made_admin = add_admin("Asha", "+919600000009").get_json()
ASHA = {"X-Admin-Key": made_admin["key"]}
client.post("/api/admin/guards", json={"name": "Mohan", "phone": "+919600000010"}, headers=ASHA)
client.post("/api/admin/guards/new-key", json={"phone": "+919600000010"}, headers=ASHA)
client.post("/api/admin/approvers", headers=ASHA,
            json={"reason": "Event", "main": "+919600000011", "backup": "+919600000012"})
say("919600000009", "KEY")
client.post("/api/admin/guards/remove", json={"phone": "+919600000010"}, headers=ADMIN)
client.post("/api/admin/admins/remove", json={"phone": "+919600000009"}, headers=ADMIN)
log_rows = client.get("/api/admin/summary", headers=ADMIN).get_json()["changes"]
seen_actions = [(c["by_whom"], c["action"]) for c in reversed(log_rows)]
assert seen_actions == [
    (access.MAIN_ADMIN, "Added an admin"),
    ("Asha +919600000009", "Added a guard"),
    ("Asha +919600000009", "Made a new gate key"),
    ("Asha +919600000009", "Changed the approvers"),
    ("KEY on WhatsApp from +919600000009", "Made a new admin key"),
    (access.MAIN_ADMIN, "Deleted a guard"),
    (access.MAIN_ADMIN, "Deleted an admin"),
], seen_actions
log_text = str(log_rows)
assert made_admin["key"] not in log_text and ADMIN_KEY_TEXT not in log_text, "no key in the log"
changes_csv = zipfile.ZipFile(io.BytesIO(client.get("/api/admin/export.zip", headers=ADMIN)
                                         .get_data())).read("admin-changes.csv").decode()
assert "Made a new admin key" in changes_csv

# A stolen gate key cannot list the allow list: 30 codes a minute for each key.
limits.forget_hits()
tries = [client.get(f"/api/staff/{1000000 + n}", headers=KEY).status_code for n in range(65)]
assert tries.count(429) == 5 and 404 in tries, tries
limits.forget_hits()
print("  bans decline waiting requests, YES cannot race a ban, offices refresh, changes logged")

print("tags divide the offices and the allow list, and change without losing a code")
limits.forget_hits()


def tag_office(new_office, new_tag, n):
    return add_office({"name": new_office, "main": f"+91970000{n:04d}",
                       "backup": f"+91971000{n:04d}", "tag": new_tag})


assert tag_office("Fees", "Admin Block", 1).status_code == 200
assert tag_office("Exams", "admin block", 2).status_code == 200
assert tag_office("Library", "", 3).status_code == 200
by_name = {o["name"]: o["tag"] for o in client.get("/api/admin/summary", headers=ADMIN)
           .get_json()["offices"]}
assert by_name == {"Fees": "Admin Block", "Exams": "Admin Block", "Library": ""}, \
    "a tag typed in another case joins the one in use"
bad_tag = tag_office("Gym", "x" * 41, 4)
assert bad_tag.status_code == 400 and "tag" in bad_tag.get_json()["fields"]
assert tag_office("Gym", "Sports\nBlock", 4).status_code == 400, "one line only"
# The visitor's list: grouped by tag, the untagged last. The flat list stays for old pages.
shown = client.get("/api/config").get_json()
assert shown["office_groups"] == [{"tag": "Admin Block", "offices": ["Exams", "Fees"]},
                                  {"tag": "", "offices": ["Library"]}], shown["office_groups"]
assert shown["offices"] == ["Exams", "Fees", "Library"]
# Retag one row, then rename a tag on every row at once.
assert client.post("/api/admin/offices/tag", json={"name": "Library", "tag": "Academic"},
                   headers=KEY).status_code == 403
moved = client.post("/api/admin/offices/tag", json={"name": "Library", "tag": "academic"},
                    headers=ADMIN)
assert moved.status_code == 200 and moved.get_json()["tag"] == "academic"
assert client.post("/api/admin/offices/tag", json={"name": "Nope", "tag": "x"},
                   headers=ADMIN).status_code == 404
renamed = client.post("/api/admin/tags/rename", headers=ADMIN,
                      json={"list": "offices", "old": "Admin Block", "new": "Main Building"})
assert renamed.status_code == 200
assert {o["name"]: o["tag"] for o in renamed.get_json()["offices"]} == {
    "Fees": "Main Building", "Exams": "Main Building", "Library": "academic"}
merged = client.post("/api/admin/tags/rename", headers=ADMIN,
                     json={"list": "offices", "old": "academic", "new": "MAIN BUILDING"})
assert {o["tag"] for o in merged.get_json()["offices"]} == {"Main Building"}, \
    "a rename to a tag in use joins the two"
assert client.post("/api/admin/tags/rename", headers=ADMIN,
                   json={"list": "offices", "old": "Gone", "new": "x"}).status_code == 404
assert client.post("/api/admin/tags/rename", headers=ADMIN,
                   json={"list": "guards", "old": "x", "new": "y"}).status_code == 400
cleared = client.post("/api/admin/tags/rename", headers=ADMIN,
                      json={"list": "offices", "old": "Main Building", "new": ""})
assert {o["tag"] for o in cleared.get_json()["offices"]} == {""}, "renamed to empty: no tag"
# The allow list: a new tag keeps the person's code, and the gate sees the tag.
physics = client.post("/api/admin/staff", headers=ADMIN, json={
    "name": "Dr Iyer", "phone": "+919400000001", "tag": "Physics"}).get_json()
assert physics["tag"] == "Physics"
iyer_code = physics["code"]
retagged = client.post("/api/admin/staff/tag", json={"code": iyer_code, "tag": "Visiting Faculty"},
                       headers=ADMIN).get_json()
iyer = [p for p in retagged["staff"] if p["code"] == iyer_code]
assert iyer and iyer[0]["tag"] == "Visiting Faculty", "same code, new tag"
assert client.get(f"/api/staff/{iyer_code}", headers=KEY).get_json()["tag"] == "Visiting Faculty"
assert tags.existing("staff") == ["Visiting Faculty"], "each list has its own tags"
assert "Visiting Faculty" not in tags.existing("offices")
summary_now = client.get("/api/admin/summary", headers=ADMIN).get_json()
logged = [c["action"] for c in summary_now["changes"]]
assert "Changed an allow list tag" in logged and "Renamed an office tag" in logged, logged
for office_name in ("Fees", "Exams", "Library"):
    client.post("/api/admin/offices/remove", json={"name": office_name}, headers=ADMIN)
client.post("/api/admin/staff/remove", json={"code": iyer_code}, headers=ADMIN)
print("  same tag in any case, retag keeps the code, rename and join, grouped visitor list")

print("WhatsApp help names only the sender's own jobs")
limits.forget_hits()
for other in visits.open_requests():
    visits.decide(other["reference"], db.DECLINED, db.BY_MAIN)
ONLY_GUARD, ONLY_APPROVER = "+919600000031", "+919600000032"
client.post("/api/admin/guards", json={"name": "Gita", "phone": ONLY_GUARD}, headers=ADMIN)
add_office({"name": "Help desk", "main": ONLY_APPROVER, "backup": ""})
APPROVER_LINE, GUARD_LINE = whatsapp.HELP_LINES["approver"][1], whatsapp.HELP_LINES["guard"][1]
KEY_LINE = "KEY sends you your key"
guard_help = say(ONLY_GUARD[1:], "hello")
assert GUARD_LINE in guard_help and KEY_LINE in guard_help and APPROVER_LINE not in guard_help
approver_help = say(ONLY_APPROVER[1:], "hello")
assert "No request is waiting for you" in approver_help, approver_help
assert APPROVER_LINE in approver_help and GUARD_LINE not in approver_help
assert KEY_LINE not in approver_help
admin_help = say(config.ADMIN_PHONE[1:], "hello")
assert admin_help == "KEY sends you your key for the admin page.", admin_help
# One number with two jobs, approver and gate desk: one message with both.
everything = say(APPROVER, "hello")
assert all(line in everything for line in (APPROVER_LINE, GUARD_LINE,
                                           "KEY sends you your key for the gate page.")), everything
assert whatsapp.help_text({"approver", "guard", "admin"}).endswith(
    "KEY sends you your keys for the gate page and the admin page."), "all three jobs"
assert GUARD_LINE in say(ONLY_GUARD[1:], "IN"), "IN with no code explains with the guard's help"
assert APPROVER_LINE not in say(ONLY_GUARD[1:], "IN")
sent_before = len(sent)
client.post("/webhook/whatsapp", json=inbound(STRANGER, "hello"))
assert len(sent) == sent_before, "a stranger gets no reply"
# Every message the app sent in this whole run fits in one WhatsApp message.
assert all(len(body) <= 4096 for _, body in sent), max(len(body) for _, body in sent)
client.post("/api/admin/guards/remove", json={"phone": ONLY_GUARD}, headers=ADMIN)
client.post("/api/admin/offices/remove", json={"name": "Help desk"}, headers=ADMIN)
print("  guard, approver, admin and all three each get their own help; strangers get nothing")

print("shared lookups cost O(1) and no caller can change them")
shared_code = add_staff("Shared Sam", "+919400000099").get_json()["code"]
first_look = staff.by_code(shared_code)
first_look["name"] = "Changed by a caller"
assert staff.by_code(shared_code)["name"] == "Shared Sam", "a copy, so the index stays right"
# noinspection PyProtectedMember
assert staff._by_code() is staff._by_code(), "one shared index, not a copy for each call"
# noinspection PyProtectedMember
assert isinstance(blacklist._keys(), frozenset)
try:
    # noinspection PyProtectedMember
    staff._by_code()[shared_code]["name"] = "x"
    raise AssertionError("the shared index must be read-only")
except TypeError:
    pass
client.post("/api/admin/staff/remove", json={"code": shared_code}, headers=ADMIN)
assert staff.by_code(shared_code) is None, "a write makes the index stale at once"
print("  one index for all callers, read-only, rebuilt after each write")

print("only super admins download the logs, and the gate never sees a visitor's phone")
limits.forget_hits()
plain_admin = client.post("/api/admin/admins", headers=ADMIN,
                          json={"name": "Plain Admin", "phone": "+919300000009"}).get_json()
plain_key = {"X-Admin-Key": plain_admin["key"]}
for log_path in ("/api/admin/export.zip", "/api/admin/export.csv", "/api/admin/staff-entries.csv"):
    assert client.get(log_path, headers=plain_key).status_code == 409, log_path
    assert client.get(log_path, headers=ADMIN).status_code == 200, log_path
# Admins and faces are for super admins only: a regular admin gets 409 for each.
for admin_path, admin_body in (("/api/admin/admins", {"name": "X", "phone": "+919300000010"}),
                               ("/api/admin/admins/new-key", {"phone": "+919300000009"}),
                               ("/api/admin/admins/remove", {"phone": "+919300000009"})):
    refused_admin = client.post(admin_path, json=admin_body, headers=plain_key)
    assert refused_admin.status_code == 409, admin_path
photographed = approved()
client.post(f"/api/pass/{entry_of(photographed)}/entry", headers=KEY, json=PHOTO)
photo_path = f"/api/admin/photo/{photographed['reference']}"
assert client.get(photo_path, headers=plain_key).status_code == 409
assert client.get(photo_path, headers=ADMIN).status_code == 200
gate_pass = client.get(f"/api/pass/{entry_of(approved())}", headers=KEY).get_json()
assert "phone" not in gate_pass and gate_pass["name"], gate_pass
# On WhatsApp too: a guard's lookup has no phone. An approver, who has it already, keeps it.
looked_up = approved()
guard_reply = say(APPROVER, entry_of(looked_up))
assert looked_up["name"] in guard_reply and "Phone:" not in guard_reply, guard_reply
# This approver handles Delivery only, so the lookup rules below can tell theirs from others'.
delivery_only = {"reason": "Delivery", "main": "+919300000003", "backup": ""}
assert client.post("/api/admin/approvers", headers=ADMIN, json=delivery_only).status_code == 200
theirs = client.post("/api/requests", json={**payload, "reason": "Delivery",
                                             "visiting": "Front office"}).get_json()["reference"]
approver_reply = say("919300000003", theirs)
assert "Phone: 9876543210" in approver_reply, approver_reply
# Another reason's request reads as no pass at all, so references cannot be tried one by one.
assert say("919300000003", looked_up["reference"]) == f"No pass has code {looked_up['reference']}."
print("  409 for a plain admin, 200 for a super, no phone for a guard on the page or WhatsApp")

print("every key-protected route refuses a missing key and the wrong kind of key")
limits.forget_hits()
SUPER_ONLY_ROUTES = {"/api/admin/decide", "/api/admin/admins", "/api/admin/admins/new-key",
                     "/api/admin/admins/remove", "/api/admin/admins/super",
                     "/api/admin/export.csv", "/api/admin/export.zip",
                     "/api/admin/staff-entries.csv", "/api/admin/photo/<reference>"}
checked = 0
for rule in application.app.url_map.iter_rules():
    path = rule.rule
    gate_side = path.startswith(("/api/pass/", "/api/gate/", "/api/staff/"))
    if not (path.startswith("/api/admin/") or gate_side):
        continue
    url = re.sub(r"<[^>]+>", "VR-12345", path)
    for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
        wrong = ADMIN if gate_side else KEY
        for headers in ({}, wrong, {"X-Admin-Key": "x" * 30, "X-Gate-Key": "y" * 30}):
            answer = client.open(url, method=method, headers=headers, json={})
            assert answer.status_code == 403, (method, path, headers, answer.status_code)
        if path in SUPER_ONLY_ROUTES:
            super_answer = client.open(url, method=method, headers=plain_key, json={})
            assert super_answer.status_code == 409, (method, path)
        checked += 1
    limits.forget_hits()
assert checked >= 29, checked  # every route today; a new one adds to it
print(f"  {checked} routes: no key, a wrong key and the other page's key all get 403")

finish()

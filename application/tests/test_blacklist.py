"""The blacklist, at the visitor page, the gate and WhatsApp.

Run: .venv\\Scripts\\python.exe tests\\test_blacklist.py"""

import io
import zipfile

# The kit comes first: it sets the settings and a clean database before the app loads.
from kit import (
    ADMIN, APPROVER, JPEG, KEY, PHOTO, add_black, add_staff, approved,
    client, csv_rows, entry_of, finish, new_request, older, payload, say,
    snap,
)
from routes import access
from models import blacklist
from core import config
from core import db
from models import entries
from core import limits
from core import migrations
from models import visits

print("a blacklisted number cannot ask, cannot enter, and the gate is told")
limits.forget_hits()
# One number, however it is typed. Python and the SQL of migration 8 agree on every form.
SAME_NUMBER = ("98765 43210", "+919876543210", "098765 43210", "0091 98765 43210",
               "919876543210")
assert {blacklist.number_key(typed) for typed in SAME_NUMBER} == {"919876543210"}
assert blacklist.number_key("12345") is None
KEY_FORMS = (*SAME_NUMBER, "+44 20 7946 0958", "+1 202 555 0143", "+91 202 555 0143",
             "00 44 20 7946 0958", "1234567890123")
with db.connect() as conn:
    for typed in KEY_FORMS:
        in_sql = conn.execute("SELECT phone_number_key(%s) AS k", (typed,)).fetchone()["k"]
        assert in_sql == blacklist.number_key(typed), (typed, in_sql)
# Two countries whose numbers share the last 10 digits are two numbers.
assert blacklist.number_key("+1 202 555 0143") != blacklist.number_key("+91 202 555 0143")




before_ban = approved()
waiting_ban = new_request()
assert add_black("+919876543210", with_key=KEY).status_code == 403
bad = add_black("123", "", "line\nbreak")
assert bad.status_code == 400 and set(bad.get_json()["fields"]) == {"phone", "name", "reason"}
listed_now = add_black("+91 98765 43210")
assert listed_now.status_code == 200, listed_now.get_json()
assert [b["number_key"] for b in listed_now.get_json()["blacklist"]] == ["919876543210"]
assert add_black("9876543210").status_code == 400, "one number once"
# The form's 10 digits match the +91 number. The page gets a neutral answer.
refused_request = client.post("/api/requests", json=payload)
assert refused_request.status_code == 403, refused_request.get_json()
assert "cannot request a visit" in refused_request.get_json()["error"]
assert "blacklist" not in refused_request.get_data(as_text=True).lower(), "it does not say why"
# A pass approved before the ban: the gate sees it, and the entry is refused everywhere.
seen_pass = client.get(f"/api/pass/{entry_of(before_ban)}", headers=KEY).get_json()
assert seen_pass["blacklisted"] is True
refused_entry = client.post(f"/api/pass/{entry_of(before_ban)}/entry", headers=KEY, json=PHOTO)
assert refused_entry.status_code == 409 and "blacklist" in refused_entry.get_json()["error"]
assert "blacklist" in say(APPROVER, f"IN {entry_of(before_ban)}")
assert "blacklist" in say(APPROVER, entry_of(before_ban)), "a lookup says so too"
# Banned between IN and the photo: the database statement itself refuses.
client.post("/api/admin/blacklist/remove", json={"phone": "9876543210"}, headers=ADMIN)
say(APPROVER, f"IN {entry_of(before_ban)}")
add_black("9876543210")
assert "blacklist" in snap(APPROVER)
assert visits.get(before_ban["reference"])["status"] == "approved"
with db.connect() as conn:
    conn.execute("DELETE FROM blacklist")
assert entries.check_in(before_ban["reference"], "test", JPEG) is not None, "off the list, it works"
add_black("9876543210")
say(APPROVER, f"YES {waiting_ban['reference']}")
assert entries.check_in(waiting_ban["reference"], "test", JPEG) is None, "the UPDATE checks too"
# The blacklist wins over the allow list.
allowed_phone = "+919876543210"
assert "blacklist" in add_staff("Kiran", allowed_phone).get_json()["fields"]["phone"]
client.post("/api/admin/blacklist/remove", json={"phone": "9876543210"}, headers=ADMIN)
kiran_code = add_staff("Kiran", allowed_phone).get_json()["code"]
add_black("9876543210")
assert "blacklist" in say(APPROVER, kiran_code)
banned_entry = client.post(f"/api/staff/{kiran_code}/scan", headers=KEY)
assert banned_entry.status_code == 409
# The refusal names the person for the gate's banner, never their number.
assert banned_entry.get_json()["name"] == "Kiran" and banned_entry.get_json()["blacklisted"] is True
assert "phone" not in banned_entry.get_json()
assert client.get(f"/api/staff/{kiran_code}", headers=KEY).get_json()["blacklisted"] is True
# Off the list again, everything works.
gone = client.post("/api/admin/blacklist/remove", json={"phone": "+919876543210"}, headers=ADMIN)
assert gone.status_code == 200 and gone.get_json()["blacklist"] == []
assert client.post("/api/admin/blacklist/remove", json={"phone": "9876543210"},
                   headers=ADMIN).status_code == 404
assert client.post("/api/requests", json=payload).status_code == 201
client.post("/api/admin/staff/remove", json={"code": kiran_code}, headers=ADMIN)
print("  no request, no entry by page, WhatsApp, photo or allow list code; lookups say so")

print("each time the blacklist stops someone, the admin page shows it")
limits.forget_hits()
with db.connect() as conn:
    conn.execute("DELETE FROM blocked_attempts")
stopped_visit = approved()
caught_code = add_staff("Kiran", "+919876543210").get_json()["code"]
add_black("9876543210")


def attempts():
    return client.get("/api/admin/summary", headers=ADMIN).get_json()["blocked"]


assert client.post("/api/requests", json=payload).status_code == 403
first = attempts()[0]
assert first["what"] == blacklist.ASKED and first["by_whom"] == blacklist.VISITOR_PAGE
assert attempts()[0]["name"] == payload["name"] and attempts()[0]["phone"] == payload["phone"]
# A board tap by reference is not an attempt. The entry code is: the person is at the gate.
client.get(f"/api/pass/{stopped_visit['reference']}", headers=KEY)
assert len(attempts()) == 1, "a board tap records nothing"




client.get(f"/api/pass/{entry_of(stopped_visit)}", headers=KEY)
assert attempts()[0]["what"] == blacklist.AT_GATE and attempts()[0]["by_whom"] == access.DESK_KEY
assert attempts()[0]["detail"] == stopped_visit["reference"]
# The same person again within 10 minutes is one attempt, so hammering does not fill the list.
client.post(f"/api/pass/{entry_of(stopped_visit)}/entry", headers=KEY, json=PHOTO)
say(APPROVER, f"IN {entry_of(stopped_visit)}")
assert len(attempts()) == 2, [a["what"] for a in attempts()]
older()
say(APPROVER, f"IN {entry_of(stopped_visit)}")
assert attempts()[0]["by_whom"] == f"Gate desk {config.GUARD}", "WhatsApp names the guard"
older()
say(APPROVER, entry_of(stopped_visit))
say(APPROVER, stopped_visit["reference"])
assert len(attempts()) == 4, "lookup by entry code counts, by reference does not"
say(APPROVER, caught_code)
older()
client.get(f"/api/staff/{caught_code}", headers=KEY)
older()
client.post(f"/api/staff/{caught_code}/scan", headers=KEY)
assert [a["what"] for a in attempts()[:3]] == [blacklist.ALLOW_CODE] * 3
assert attempts()[0]["detail"] == caught_code
assert len(attempts()) == 7, [a["what"] for a in attempts()]
# The log download holds them all. The retention period deletes them.
attempt_csv = zipfile.ZipFile(io.BytesIO(client.get("/api/admin/export.zip", headers=ADMIN)
                                         .get_data())).read("blocked-attempts.csv").decode()
assert len(csv_rows(attempt_csv)) == 7, attempt_csv
with db.connect() as conn:
    conn.execute("UPDATE blocked_attempts SET at = %s", (db.ago(2),))
visits.purge_old()
assert attempts() == []
client.post("/api/admin/blacklist/remove", json={"phone": "9876543210"}, headers=ADMIN)
client.post("/api/admin/staff/remove", json={"code": caught_code}, headers=ADMIN)
print("  request, gate page, WhatsApp IN, entry code lookup and allow list code each recorded")

print("a blacklisted number never blocks the approval of another number")
limits.forget_hits()
add_black("9123400000")
other_number = new_request()
approved_reply = say(APPROVER, f"YES {other_number['reference']}")
assert "is now approved" in approved_reply, "the approval checks the visit's own number"
with db.connect() as conn:
    conn.execute("DELETE FROM blacklist")
db.forget_cache()

print("the blacklist goes by the number only: one name on two numbers is two people")
limits.forget_hits()
assert add_black("+91 98111 00000", payload["name"]).status_code == 200
# Another person with the same name, on another number, can ask and can enter.
twin_request = client.post("/api/requests", json={**payload, "phone": "9822200000"})
assert twin_request.status_code == 201, twin_request.get_json()
twin_code = add_staff(payload["name"], "+919822200001").get_json()["code"]
twin_scan = client.post(f"/api/staff/{twin_code}/scan", headers=KEY)
twin_seen = twin_scan.get_json()
assert twin_scan.status_code == 200 and twin_seen["kind"] == "entry", twin_seen
# The listed number with another name typed is still refused.
renamed = client.post("/api/requests",
                      json={**payload, "name": "Someone Else", "phone": "9811100000"})
assert renamed.status_code == 403, renamed.get_json()
client.post("/api/admin/blacklist/remove", headers=ADMIN, json={"phone": "+91 98111 00000"})
client.post("/api/admin/staff/remove", json={"code": twin_code}, headers=ADMIN)
print("  same name on another number passes; another name on the listed number is refused")

print("the blacklist keeps two countries apart, and migration 8 converts old rows")
limits.forget_hits()
# A ban on a US number does not stop an Indian number with the same last 10 digits.
assert add_black("+1 202 555 0143", "US caller").status_code == 200
same_tail = client.post("/api/requests", json={**payload, "phone": "+91 202 555 0143"})
assert same_tail.status_code == 201, same_tail.get_json()
assert client.post("/api/requests", json={**payload, "phone": "+1 202 555 0143"}).status_code == 403
assert add_black("+91 202 555 0143", "Indian caller").status_code == 200, "both can be listed"
client.post("/api/admin/blacklist/remove", headers=ADMIN, json={"phone": "+1 202 555 0143"})
client.post("/api/admin/blacklist/remove", headers=ADMIN, json={"phone": "+91 202 555 0143"})
# Migration 8 on rows written by the old version: build steps 1 to 7 in a scratch schema,
# add old-style rows, run step 8, and read the new keys.
with db.connect() as conn:
    conn.execute("CREATE SCHEMA old_shape")
    conn.execute("SET LOCAL search_path TO old_shape")
    for old_step in migrations.MIGRATIONS[:7]:
        conn.execute(old_step)
    for old_phone in ("+91 98765 43210", "9123456780", "+44 20 7946 0958"):
        conn.execute("INSERT INTO blacklist (phone_key, phone, name, reason, added_at)"
                     " VALUES (%s, %s, 'Old', '', %s)",
                     (blacklist.phone_key(old_phone), old_phone, db.now()))
    conn.execute(migrations.MIGRATIONS[7])
    converted = {row["phone"]: row["number_key"] for row in
                 conn.execute("SELECT phone, number_key FROM blacklist").fetchall()}
    conn.execute("SET LOCAL search_path TO public")
    conn.execute("DROP SCHEMA old_shape CASCADE")
assert converted == {"+91 98765 43210": "919876543210", "9123456780": "919123456780",
                     "+44 20 7946 0958": "442079460958"}, converted
print("  US and Indian numbers with one tail stay apart; old rows get their full key")

finish()

"""Approvers, automatic approval, pass time, forgotten keys and bulk decisions.

Run: .venv\\Scripts\\python.exe tests\\test_approvals.py"""

import contextlib
import io
from datetime import datetime, timedelta, timezone

# The kit comes first: it sets the settings and a clean database before the app loads.
from kit import (
    ADMIN, APPROVER, JPEG, KEY, PHOTO, STRANGER, add_admin, add_black,
    approved, broken, client, entry_of, exit_of, finish, inbound, made_hours_ago,
    new_request, payload, say, sent, snap, templates,
)
import app as application
from routes import access
from core import config
from core import db
from models import entries
from core import limits
from models import people
from services import timer
from models import visits
from services import whatsapp

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
    made_hours_ago(late, 1)
    timer.escalate_due()
    assert templates[-1][0] == DELIVERY_BACKUP, templates[-1]
    assert templates[-1][1][0] == late["reference"]
finally:
    config.APPROVERS = real_approvers
print("  routing, deciding, waiting lists and escalation all follow the reason")

print("the admin page changes a reason's two approvers")
NEW_MAIN, NEW_BACKUP = "+919000000011", "+919000000012"


def set_pair(main_number, backup_number, reason="Event", key=None):
    return client.post("/api/admin/approvers", headers=key or ADMIN,
                       json={"reason": reason, "main": main_number, "backup": backup_number})


assert set_pair(NEW_MAIN, NEW_BACKUP, key=KEY).status_code == 403
assert set_pair(NEW_MAIN, NEW_BACKUP, reason="Party").status_code == 400
for bad_main, bad_backup, field in (("", NEW_BACKUP, "main"), (NEW_MAIN, "123", "backup"),
                                    ("98765", NEW_BACKUP, "main"),
                                    (NEW_MAIN, "+91 90000 00011", "backup")):
    refused = set_pair(bad_main, bad_backup)
    assert refused.status_code == 400 and field in refused.get_json()["fields"], field
assert "Leave the backup empty" in set_pair(NEW_MAIN, NEW_MAIN).get_json()["fields"]["backup"]
# An empty backup: the approver is both, and the escalation is a reminder to them.
alone = set_pair(NEW_MAIN, "")
assert alone.status_code == 200
assert {"reason": "Event", "main": NEW_MAIN, "backup": NEW_MAIN,
        "auto_minutes": None} in alone.get_json()["approvers"]
lonely = client.post("/api/requests", json={**payload, "reason": "Event"}).get_json()
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 (db.ago(1 / 24), lonely["reference"]))
db.forget_cache()
timer.escalate_due()
assert templates[-1][0] == NEW_MAIN and templates[-1][1][1].startswith("Reminder:"), templates[-1]
visits.decide(lonely["reference"], db.DECLINED, db.BY_MAIN)
saved = set_pair("+91 90000-00011", NEW_BACKUP)
assert saved.status_code == 200, saved.get_json()
event_row = {"reason": "Event", "main": NEW_MAIN, "backup": NEW_BACKUP, "auto_minutes": None}
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
print("  numbers checked, an empty backup reminds the approver, the old number refused")

print("a request made in working hours is approved by itself")


def ist(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=config.WORK_TIMEZONE)


# Monday 5, Saturday 10 and Sunday 11 October 2026.
assert timer.auto_approve_time(ist(5, 9, 59), 30) is None
assert timer.auto_approve_time(ist(5, 10), 30) == "2026-10-05T05:00:00+00:00"
assert timer.auto_approve_time(ist(5, 16, 59), 30) == "2026-10-05T11:59:00+00:00"
assert timer.auto_approve_time(ist(5, 17), 30) is None
assert timer.auto_approve_time(ist(10, 12), 30) is not None
assert timer.auto_approve_time(ist(11, 12), 30) is None
# 04:30 UTC is 10:00 in India, so it counts.
assert timer.auto_approve_time(datetime(2026, 10, 5, 4, 30, tzinfo=timezone.utc), 30) \
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
timer.auto_approve_time = lambda _moment, _minutes: "2999-01-01T00:00:00+00:00"
in_hours = client.post("/api/requests", json=payload)
timer.auto_approve_time = real_auto_time
assert in_hours.status_code == 201
assert visits.get(in_hours.get_json()["reference"])["auto_approve_at"], "the server keeps the time"
assert not private & in_hours.get_json().keys(), "the new request must not tell the visitor"
print("  10:00 to 16:59 Monday to Saturday only, a NO first wins, approvers told once")

print("the backup always gets half the time before an automatic approval")


def made_with_auto(minutes_ago: float, auto_minutes: float) -> str:
    """A waiting request made minutes_ago, approved by itself auto_minutes after it, or never."""
    ticket = new_request()
    made = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    auto = (made + timedelta(minutes=auto_minutes)).isoformat(timespec="seconds") \
        if auto_minutes else None
    with db.connect() as writer:
        writer.execute("UPDATE visits SET created_at = %s, auto_approve_at = %s"
                       " WHERE reference = %s",
                       (made.isoformat(timespec="seconds"), auto, ticket["reference"]))
    db.forget_cache()
    return ticket["reference"]


# 3 minutes: the backup is asked after 1.5. Before, it waited 15, after the approval.
short = made_with_auto(2, 3)
too_soon = made_with_auto(1, 3)
# A long time, or none out of hours: the backup is asked after ESCALATE_MINUTES, as before.
wait = config.ESCALATE_MINUTES
long_one = made_with_auto(wait + 5, 4 * wait)
long_young = made_with_auto(wait - 5, 4 * wait)
out_of_hours = made_with_auto(wait - 5, 0)
due_now = {visit["reference"] for visit in visits.due_for_escalation()}
assert {short, long_one} <= due_now, due_now
assert not {too_soon, long_young, out_of_hours} & due_now, due_now
timer.escalate_due()
assert visits.get(short)["status"] == db.ESCALATED, "asked again before it approves by itself"
assert visits.get(too_soon)["status"] == db.PENDING
# The timer wakes at the halfway point, not 15 minutes after the request.
with db.connect() as conn:
    conn.execute("UPDATE visits SET status = %s WHERE status = %s AND reference <> %s",
                 (db.DECLINED, db.PENDING, too_soon))
db.forget_cache()
halfway = datetime.fromisoformat(visits.get(too_soon)["created_at"]) + timedelta(seconds=90)
assert visits.next_due() == halfway, (visits.next_due(), halfway)
print("  3 minutes: the backup after 1.5. A long time or none: after ESCALATE_MINUTES")

print("each reason and each office has its own time to approve by itself")
student = {"reason": "See a student", "office": None}
table = people.approver_table()
assert people.auto_minutes_for(table, student) == config.AUTO_APPROVE_MINUTES == 30
assert next(row for row in client.get("/api/admin/summary", headers=ADMIN).get_json()["approvers"]
            if row["reason"] == "See a student")["auto_minutes"] is None, "not set: the default"
pair = {"reason": "See a student", "main": "+" + APPROVER, "backup": ""}
for wrong in ("abc", "-5", "2000", "1.5", True):
    refused_time = client.post("/api/admin/approvers", headers=ADMIN,
                               json={**pair, "auto_minutes": wrong})
    assert refused_time.status_code == 400, wrong
    assert "0 means never" in refused_time.get_json()["fields"]["auto_minutes"], wrong

# An open request that approves by itself moves to the new time. One with no time keeps none.
waits, out_of_hours = new_request(), new_request()
created = datetime.fromisoformat(visits.get(waits["reference"])["created_at"])
with db.connect() as conn:
    conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                 (timer.after(created, 30), waits["reference"]))
    # Made out of hours: no time. Set here, so the test passes at any hour.
    conn.execute("UPDATE visits SET auto_approve_at = NULL WHERE reference = %s",
                 (out_of_hours["reference"],))
db.forget_cache()
set_time = client.post("/api/admin/approvers", headers=ADMIN, json={**pair, "auto_minutes": "45"})
assert set_time.status_code == 200, set_time.get_json()
assert next(row for row in set_time.get_json()["approvers"]
            if row["reason"] == "See a student")["auto_minutes"] == 45
assert people.auto_minutes_for(people.approver_table(), student) == 45
assert visits.get(waits["reference"])["auto_approve_at"] == timer.after(created, 45)
assert visits.get(out_of_hours["reference"])["auto_approve_at"] is None
assert "after 45 minutes" in client.get("/api/admin/summary", headers=ADMIN).get_json()[
    "changes"][0]["detail"], "the change log says it"
# Other reasons keep the default, and a typed-in reason uses Other's time.
assert people.auto_minutes_for(people.approver_table(), {"reason": "Delivery"}) == 30
client.post("/api/admin/approvers", headers=ADMIN,
            json={"reason": "Other", "main": "+" + APPROVER, "backup": "", "auto_minutes": 10})
assert people.auto_minutes_for(people.approver_table(), {"reason": "A parcel"}) == 10
# 0: a person must decide. The open request stops waiting for the timer.
client.post("/api/admin/approvers", headers=ADMIN, json={**pair, "auto_minutes": 0})
assert visits.get(waits["reference"])["auto_approve_at"] is None
assert people.auto_minutes_for(people.approver_table(), student) == 0
assert timer.auto_approve_time(datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc), 0) is None
# The message to the approvers names the time of that reason.
client.post("/api/admin/approvers", headers=ADMIN, json={**pair, "auto_minutes": 20})
with db.connect() as conn:
    conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", out_of_hours["reference"]))
db.forget_cache()
before = len(sent)
timer.auto_approve_due()
assert any("within 20 minutes" in body for _, body in sent[before:]), sent[before:]
# Empty goes back to the default.
client.post("/api/admin/approvers", headers=ADMIN, json={**pair, "auto_minutes": ""})
client.post("/api/admin/approvers", headers=ADMIN,
            json={"reason": "Other", "main": "+" + APPROVER, "backup": "", "auto_minutes": None})
assert people.approver_table()["auto"]["reasons"] == {}
# An office has its own time, set by the office's Time button.
office = {"name": "Exams", "main": "+919000000041", "backup": ""}
assert client.post("/api/admin/offices", headers=ADMIN, json=office).status_code == 200
at_exams = {"reason": config.OFFICE_REASON, "office": "Exams"}
assert people.auto_minutes_for(people.approver_table(), at_exams) == 30
timed = client.post("/api/admin/offices/auto", headers=ADMIN,
                    json={"name": "Exams", "auto_minutes": "15"})
assert timed.status_code == 200, timed.get_json()
assert [o["auto_minutes"] for o in timed.get_json()["offices"] if o["name"] == "Exams"] == [15]
assert people.auto_minutes_for(people.approver_table(), at_exams) == 15
assert client.post("/api/admin/offices/auto", headers=ADMIN,
                   json={"name": "Nowhere", "auto_minutes": 5}).status_code == 404
assert client.post("/api/admin/offices/auto", headers=ADMIN,
                   json={"name": "Exams", "auto_minutes": "x"}).status_code == 400
assert client.post("/api/admin/offices/auto", json={"name": "Exams"}).status_code == 403
# A request for Exams, made in working hours: it approves by itself after the office's 15.
exams_made = datetime.now(timezone.utc).replace(microsecond=0)
exams_visit = visits.create({**{key: payload[key] for key in ("name", "phone", "address")},
                             "reason": config.OFFICE_REASON, "visiting": "Exams"}, [],
                            timer.after(exams_made, 15), "Exams")
client.post("/api/admin/offices/remove", headers=ADMIN, json={"name": "Exams"})
# The office is gone: the request goes to "Other", with the time of "Other", 30 minutes.
moved_to = visits.get(exams_visit["reference"])["auto_approve_at"]
assert moved_to == timer.after(datetime.fromisoformat(exams_visit["created_at"]), 30), moved_to
say(APPROVER, f"NO {exams_visit['reference']}")
for case in (waits, out_of_hours):
    say(APPROVER, f"NO {case['reference']}")
print("  default 30, 0 means never, open requests move, offices too, the change log says it")

print("a pass works for PASS_HOURS after the request, then never again")
assert config.PASS_HOURS == 48
assert client.get("/api/config").get_json()["pass_hours"] == 48


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
                         headers={"True-Client-IP": f"10.0.0.{n}"}).status_code
             for n in range(11)]
finally:
    config.BEHIND_PROXY = False
    limits.forget_hits()
assert codes == [200] * 10 + [429], codes

# Behind Render, True-Client-IP decides, not the last X-Forwarded-For entry.
config.BEHIND_PROXY = True
try:
    with application.app.test_request_context(headers={
            "True-Client-IP": "203.0.113.7",
            "X-Forwarded-For": "198.51.100.1, 203.0.113.7, 172.70.1.1, 10.1.2.3"}):
        assert limits.caller() == "203.0.113.7", limits.caller()
    # Without the header, a forged X-Forwarded-For counts for nothing: all share one address.
    with application.app.test_request_context(headers={"X-Forwarded-For": "1.1.1.1, 10.1.2.3"},
                                              environ_base={"REMOTE_ADDR": "10.9.9.9"}):
        assert limits.caller() == "10.9.9.9", limits.caller()
    # Behind a server the university runs, the setting names its proxy's own header.
    config.CLIENT_IP_HEADER = "X-Real-IP"
    with application.app.test_request_context(headers={
            "X-Real-IP": "198.51.100.4", "True-Client-IP": "6.6.6.6"}):
        assert limits.caller() == "198.51.100.4", "a header the proxy does not set is ignored"
    config.CLIENT_IP_HEADER = "X-Forwarded-For"
    with application.app.test_request_context(headers={
            "X-Forwarded-For": "6.6.6.6, 198.51.100.5", "True-Client-IP": "6.6.6.6"}):
        assert limits.caller() == "198.51.100.5", "only the entry the proxy added counts"
    config.CLIENT_IP_HEADER = ""
    # One visitor behind many Render proxies is one caller.
    statuses = [client.get("/api/health", headers={
        "True-Client-IP": "203.0.113.9", "X-Forwarded-For": f"203.0.113.9, 10.0.0.{proxy}"}
    ).status_code for proxy in range(31)]
    assert statuses[-1] == 429, "31 health checks a minute from one visitor are refused"
finally:
    config.BEHIND_PROXY = False
    limits.forget_hits()
print("  behind Render, the visitor is True-Client-IP, not the proxy")
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

print("approvals on WhatsApp in any case, with the marks a phone adds")
limits.forget_hits()
small_yes, small_no, dotted = new_request(), new_request(), new_request()
assert "is now approved" in say(APPROVER, f"yes {small_yes['reference'].lower()}")
assert "is now declined" in say(APPROVER, f"No, {small_no['reference']}.")
assert "is now approved" in say(APPROVER, f"Yes {dotted['reference']}.")
assert visits.get(dotted["reference"])["status"] == "approved"
only_one = new_request()
for other in visits.open_requests():
    if other["reference"] != only_one["reference"]:
        visits.decide(other["reference"], db.DECLINED, db.BY_MAIN)
say(APPROVER, "Yes, but wait")
assert visits.get(only_one["reference"])["status"] == "pending", \
    "words that are not a reference never decide the one waiting request"
assert "is now approved" in say(APPROVER, "yes!"), "YES alone still decides the only one"
print("  yes, Yes., No, and yes! all read; stray words never decide")

print("a super admin approves or declines many requests at once")
limits.forget_hits()
with db.connect() as conn:
    conn.execute("DELETE FROM admins")
db.forget_cache()
plain = add_admin("Ravi", "+919600000020").get_json()
RAVI_ADMIN = {"X-Admin-Key": plain["key"]}
boss = add_admin("Uma", "+919600000021").get_json()
UMA = {"X-Admin-Key": boss["key"]}
# Only a super admin makes a super admin. Nobody changes their own role.
assert client.post("/api/admin/admins/super", json={"phone": "+919600000021", "super": True},
                   headers=RAVI_ADMIN).status_code == 409, "409, so the page keeps Ravi's key"
promoted = client.post("/api/admin/admins/super", json={"phone": "+919600000021", "super": True},
                       headers=ADMIN)
assert promoted.status_code == 200
assert {a["phone"]: a["super"] for a in promoted.get_json()["admins"]} == {
    "+919600000020": False, "+919600000021": True}
assert client.get("/api/admin/summary", headers=UMA).get_json()["super"] is True
assert client.get("/api/admin/summary", headers=RAVI_ADMIN).get_json()["super"] is False
assert client.post("/api/admin/admins/super", json={"phone": "+919600000021", "super": False},
                   headers=UMA).status_code == 409, "not on yourself"
# A regular admin cannot take a super admin's place with a new key, nor delete them.
for path in ("/api/admin/admins/new-key", "/api/admin/admins/remove"):
    refused_super = client.post(path, json={"phone": "+919600000021"}, headers=RAVI_ADMIN)
    assert refused_super.status_code == 409, (path, refused_super.status_code)
assert client.get("/api/admin/summary", headers=UMA).status_code == 200, "Uma's key still works"
assert client.post("/api/admin/admins/new-key", json={"phone": "+919600000020"},
                   headers=UMA).status_code == 200, "a super admin renews a regular admin"
RAVI_ADMIN = {"X-Admin-Key": client.post("/api/admin/admins/new-key", headers=UMA,
                                         json={"phone": "+919600000020"}).get_json()["key"]}

# The bulk call: only for a super admin, and each request is checked on its own.
for other in visits.open_requests():
    visits.decide(other["reference"], db.DECLINED, db.BY_MAIN)
wave = [new_request() for _ in range(3)]
done_before = approved()
late_one = new_request()
made_hours_ago(late_one, config.PASS_HOURS + 1)
banned_one = client.post("/api/requests", json={**payload, "phone": "9123456780"}).get_json()
add_black("9123456780")
blocked_one = client.post("/api/requests", json={**payload, "phone": "9123456781"}).get_json()
with db.connect() as conn:
    conn.execute("INSERT INTO blacklist (number_key, phone_key, phone, name, reason, added_at)"
                 " VALUES ('919123456781', '9123456781', '9123456781', 'X', '', %s)",
                 (db.now(),))
db.forget_cache()
asked = [v["reference"] for v in wave] + [done_before["reference"], late_one["reference"],
                                          banned_one["reference"], blocked_one["reference"],
                                          "VR-00000"]
assert client.post("/api/admin/decide", json={"references": asked, "decision": "approve"},
                   headers=RAVI_ADMIN).status_code == 409
assert client.post("/api/admin/decide", json={"references": asked, "decision": "maybe"},
                   headers=UMA).status_code == 400
assert client.post("/api/admin/decide", json={"references": ["VR-1"] * 2 + [
    f"VR-{n}" for n in range(10000, 10101)], "decision": "approve"},
    headers=UMA).status_code == 400, "100 at most"
sent.clear()
bulk = client.post("/api/admin/decide", json={"references": asked, "decision": "approve"},
                   headers=UMA)
assert bulk.status_code == 200, bulk.get_json()
assert bulk.get_json()["decided"] == [v["reference"] for v in wave], bulk.get_json()
why = {s["reference"]: s["why"] for s in bulk.get_json()["skipped"]}
assert why == {done_before["reference"]: "Already approved.",
               late_one["reference"]: "Expired.",
               banned_one["reference"]: "Already declined.",
               blocked_one["reference"]: "The number is on the blacklist.",
               "VR-00000": "No request has this reference."}, why
decided_now = visits.get(wave[0]["reference"])
assert decided_now["decided_by"] == db.BY_ADMIN
assert decided_now["decided_phone"] == "Uma +919600000021"
visitor_text = client.get(f"/api/visit/{wave[0]['token']}").get_data(as_text=True)
assert "decided_by" not in visitor_text and "Uma" not in visitor_text, "the visitor never sees who"
# Each guard hears once, with the whole list, and never a gate code.
to_desk = [body for to, body in sent if whatsapp.same_number(to, config.GUARD)]
assert len(to_desk) == 1 and all(v["reference"] in to_desk[0] for v in wave), to_desk
wave_codes = [code for v in wave for code in visits.codes_of(v["reference"]).values()]
assert not any(code in to_desk[0] for code in wave_codes)
# Bulk decline, and the change log names the admin.
second = [new_request() for _ in range(2)]
declined_all = client.post("/api/admin/decide", headers=UMA,
                           json={"references": [v["reference"] for v in second],
                                 "decision": "decline"}).get_json()
assert declined_all["skipped"] == [] and all(
    visits.get(v["reference"])["status"] == "declined" for v in second)
log_now = client.get("/api/admin/summary", headers=ADMIN).get_json()["changes"]
assert log_now[0]["action"] == "Declined 2 requests at once" and log_now[0]["by_whom"] == \
    "Uma +919600000021"
assert log_now[1]["action"] == "Approved 3 requests at once"
# A long list is split under WhatsApp's limit.
many = [{**wave[0], "reference": f"VR-{n}", "name": "A long visitor name " * 3, "guests": []}
        for n in range(10000, 10100)]
bodies = whatsapp.guard_list_bodies(many)
assert len(bodies) > 1 and all(len(b) < 4096 for b in bodies)
assert sum(b.count("VR-") for b in bodies) == 100, "every visitor named once"
with db.connect() as conn:
    conn.execute("DELETE FROM blacklist")
    conn.execute("DELETE FROM admins")
db.forget_cache()
print("  only a super admin, each request checked alone, guards told once, all logged")

print("worst cases: a resent form, a visitor from abroad, an unexpected failure")
limits.forget_hits()
# A resend after a slow answer returns the first request, and the approver hears once.
KEY_ONE = "a" * 32
templates.clear()
first_send = client.post("/api/requests", json={**payload, "request_key": KEY_ONE})
again_send = client.post("/api/requests", json={**payload, "request_key": KEY_ONE})
assert first_send.status_code == 201 and again_send.status_code == 200, again_send.get_json()
assert again_send.get_json()["reference"] == first_send.get_json()["reference"]
assert again_send.get_json()["token"] == first_send.get_json()["token"], "the same pass"
assert len(templates) == 1, "the approver is asked once"
assert "request_key" not in first_send.get_json() and "request_key" not in again_send.get_json()
other_key = client.post("/api/requests", json={**payload, "request_key": "b" * 32}).get_json()
assert other_key["reference"] != first_send.get_json()["reference"], "a new form is a new request"
odd_key = client.post("/api/requests", json={**payload, "request_key": "short"})
assert odd_key.status_code == 201, "a key that does not look right is ignored"
gate_seen = client.get(f"/api/pass/{first_send.get_json()['reference']}", headers=KEY).get_json()
assert "request_key" not in gate_seen, "the gate never sees the key"
# A request that failed to reach the approver is deleted, so the same key can try again.
real_template = whatsapp.send_template
whatsapp.send_template = broken
try:
    failed = client.post("/api/requests", json={**payload, "request_key": "c" * 32})
    assert failed.status_code == 502
finally:
    whatsapp.send_template = real_template
assert client.post("/api/requests", json={**payload, "request_key": "c" * 32}).status_code == 201

# A visitor from abroad gives + and the country code. A short or odd number is refused.
for number, works in (("+44 7911 123456", True), ("+1 415 555 0100", True), ("+12345", False),
                      ("987654321", False), ("98765 43210", True)):
    answer = client.post("/api/requests", json={**payload, "phone": number})
    assert (answer.status_code == 201) == works, (number, answer.get_json())

# An unexpected failure answers in words the page can show, not an HTML error page.
real_create = visits.create
visits.create = broken
try:
    with contextlib.redirect_stderr(io.StringIO()):
        crashed = client.post("/api/requests", json=payload)
    assert crashed.status_code == 500 and crashed.get_json()["error"].startswith("The server had")
finally:
    visits.create = real_create
for other in visits.open_requests():
    visits.decide(other["reference"], db.DECLINED, db.BY_MAIN)
print("  one request for a resent form, + numbers from abroad, a plain answer on failure")

finish()

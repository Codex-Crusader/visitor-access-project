"""Fixes from the bug hunts and the security review.

Run: .venv\\Scripts\\python.exe tests\\test_hardening.py"""

import psycopg
import runpy

# The kit comes first: it sets the settings and a clean database before the app loads.
from kit import (
    ADMIN, APPROVER, KEY, PHOTO, approved, client, entry_of, finish,
    inbound, new_request, payload, say, sent, snap,
)
import app as application
from routes import gate as gate_routes
from models import audit
from models import blacklist
from core import checks
from core import config
from core import db
from services import export
from core import limits
from models import people
from core import redaction
from services import timer
from models import visits
from services import whatsapp

print("bugs found in the hunt stay fixed")
limits.forget_hits()
# A resend that races its first request, deleted at that moment because WhatsApp failed,
# makes a new request instead of crashing.
first_try = client.post("/api/requests", json={**payload, "request_key": "e" * 32}).get_json()
real_lookup = visits.by_request_key


def vanished(_key):
    """The first request is deleted just as the resend finds the key taken. Finds nothing."""
    visits.delete(first_try["reference"])


visits.by_request_key = vanished
try:
    fields, guests, _ = checks.clean_fields(payload)
    retried = visits.create(fields, guests, request_key="e" * 32)
finally:
    visits.by_request_key = real_lookup
assert retried["reference"] != first_try["reference"]
assert visits.by_request_key("e" * 32)["reference"] == retried["reference"]
# The same blacklisted person, typed two ways within 10 minutes, is one attempt.
with db.connect() as conn:
    conn.execute("DELETE FROM blocked_attempts")
blacklist.record_attempt("98765 43210", "K", blacklist.ASKED, "x", "Visitor page")
blacklist.record_attempt("9876543210", "K", blacklist.ASKED, "x", "Visitor page")
assert len(blacklist.recent_attempts()) == 1, blacklist.recent_attempts()
with db.connect() as conn:
    conn.execute("DELETE FROM blocked_attempts")
# A request asked again reads "Asked again" in the log, right for a backup or a reminder.
assert export.STATUS_WORDS["escalated"] == "Asked again"
print("  a raced resend, one attempt typed two ways, neutral words for asking again")

print("an uncertain WhatsApp send keeps the request, and a person must still decide")
limits.forget_hits()


def unsure(*_args, **_kwargs):
    raise whatsapp.Uncertain("No answer from WhatsApp in 15 s")


real_template, real_auto_time = whatsapp.send_template, timer.auto_approve_time
whatsapp.send_template = unsure
timer.auto_approve_time = lambda _moment, _minutes: db.now()  # as if made in working hours
try:
    kept = client.post("/api/requests", json={**payload, "request_key": "u" * 32})
finally:
    whatsapp.send_template, timer.auto_approve_time = real_template, real_auto_time
assert kept.status_code == 201, kept.get_data(as_text=True)
with db.connect() as conn:
    kept_row = conn.execute("SELECT status, auto_approve_at FROM visits WHERE reference = %s",
                            (kept.get_json()["reference"],)).fetchone()
assert kept_row["status"] == "pending" and kept_row["auto_approve_at"] is None, kept_row
# With TEMPLATE_FALLBACK on, an uncertain template is not followed by plain text: one ask only.
application.config.TEMPLATE_FALLBACK = True
whatsapp.send_template = unsure
before_count = len(sent)
try:
    whatsapp.notify(APPROVER, visits.get(kept.get_json()["reference"]))
    raise AssertionError("an uncertain send must not count as sent")
except whatsapp.Uncertain:
    pass
finally:
    whatsapp.send_template = real_template
    application.config.TEMPLATE_FALLBACK = False
assert len(sent) == before_count, sent[before_count:]


# Which answers from Meta are uncertain: no answer in time, or a fault on Meta's side.
class MetaAnswer:
    def __init__(self, http_status):
        self.status_code, self.ok, self.text = http_status, http_status < 400, "x"

    @staticmethod
    def json():
        return {}


def timed_out(*_args, **_kwargs):
    raise whatsapp.requests.ReadTimeout()


real_post = whatsapp.requests.post
try:
    for answer, expected in ((timed_out, whatsapp.Uncertain),
                             (lambda *_a, **_k: MetaAnswer(503), whatsapp.Uncertain),
                             (lambda *_a, **_k: MetaAnswer(400), RuntimeError)):
        whatsapp.requests.post = answer
        try:
            # noinspection PyProtectedMember
            whatsapp._post(APPROVER, {})
            raise AssertionError("a failed send must raise")
        except RuntimeError as failure:
            assert isinstance(failure, whatsapp.Uncertain) == (expected is whatsapp.Uncertain)
finally:
    whatsapp.requests.post = real_post
# The reminder too: an uncertain send counts as asked, so the next round does not ask again.
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 (db.ago(1), kept.get_json()["reference"]))
db.forget_cache()
reminders = []
whatsapp.send_template = lambda *args, **kwargs: reminders.append(1) or unsure()
try:
    timer.escalate_due()
    timer.escalate_due()
finally:
    whatsapp.send_template = real_template
assert visits.get(kept.get_json()["reference"])["status"] == "escalated"
assert len(reminders) == 1, "asked once, not once each round"
print("  kept, never approved by itself, asked once; a refusal from Meta is still a failure")

print("open requests go to a new approver at once")
limits.forget_hits()
first, second, third = "+919300000001", "+919300000002", "+919300000003"


def set_delivery(main, backup):
    set_answer = client.post("/api/admin/approvers", headers=ADMIN,
                             json={"reason": "Delivery", "main": main, "backup": backup})
    assert set_answer.status_code == 200, set_answer.get_data(as_text=True)


def went_to(phone, reference):
    return any(whatsapp.same_number(to, phone) and reference in body for to, body in sent)


set_delivery(first, second)
delivery = {**payload, "reason": "Delivery", "visiting": "Front office"}
waiting = client.post("/api/requests", json=delivery).get_json()["reference"]
asked_again = client.post("/api/requests", json=delivery).get_json()["reference"]
visits.mark_escalated(asked_again)
sent.clear()
set_delivery(third, second)
assert went_to(third, waiting), "a waiting request goes to the new approver"
assert not any(asked_again in body for _, body in sent), "its backup did not change"
sent.clear()
set_delivery(third, first)
assert went_to(first, asked_again), "an asked-again request goes to the new backup"
assert not any(waiting in body for _, body in sent), "the approver did not change"
sent.clear()
set_delivery(third, first)
assert not sent, "no change, nothing sent"
assert any("Open requests sent to them: 1" in change["detail"] for change in audit.everything())
# The approver change log keeps the numbers before the change.
assert any("Delivery: from +919300000003, backup +919300000002, to +919300000003, backup"
           " +919300000001" in change["detail"] for change in audit.everything())
# A deleted office's open requests go to the approvers for Other, and are sent to them.
client.post("/api/admin/offices", headers=ADMIN,
            json={"name": "Hostel Office", "main": "+919300000004", "backup": ""})
hostel = client.post("/api/requests", json={
    **payload, "reason": "See an office", "office": "Hostel Office"}).get_json()["reference"]
sent.clear()
client.post("/api/admin/offices/remove", headers=ADMIN, json={"name": "Hostel Office"})
assert went_to(people.approver_table()["reasons"]["Other"][0], hostel), sent
print("  waiting to the new approver, asked again to the new backup, a deleted office to Other")

print("one photo, one visitor: a second IN waits for the first photo")
limits.forget_hits()
first_in, second_in = approved(), approved()
assert "Take a photo of" in say(APPROVER, f"IN {entry_of(first_in)}")
owed = say(APPROVER, f"IN {entry_of(second_in)}")
assert first_in["reference"] in owed and "CANCEL" in owed, owed
snap(APPROVER)
assert visits.get(first_in["reference"])["status"] == "inside", "the photo went to the first IN"
assert visits.get(second_in["reference"])["status"] == "approved"
# The same IN twice only refreshes the wait. CANCEL drops it and lets nobody in.
assert "Take a photo of" in say(APPROVER, f"IN {entry_of(second_in)}")
assert "Take a photo of" in say(APPROVER, f"in {entry_of(second_in)}")
assert "nobody was let in" in say(APPROVER, "cancel")
assert visits.get(second_in["reference"])["status"] == "approved"
assert "No photo is waiting" in say(APPROVER, "CANCEL")
# An expired wait, or one for a pass that can no longer enter, never blocks.
third_in = approved()
say(APPROVER, f"IN {entry_of(second_in)}")
with db.connect() as wait_writer:
    wait_writer.execute("UPDATE photo_waits SET asked = %s", (db.ago(1),))
assert "Take a photo of" in say(APPROVER, f"IN {entry_of(third_in)}")
client.post(f"/api/pass/{entry_of(third_in)}/entry", headers=KEY, json=PHOTO)
assert "Take a photo of" in say(APPROVER, f"IN {entry_of(second_in)}"), "third is inside now"
say(APPROVER, "CANCEL")
assert "CANCEL" in whatsapp.help_text({"guard"})
print("  refused with the pending name, CANCEL drops it, expired or entered waits give way")

print("a gate key opens only the board by reference, and lookups have a limit")
limits.forget_hits()
on_board_visit = approved()
assert client.get(f"/api/pass/{on_board_visit['reference']}", headers=KEY).status_code == 200
waiting_visit = new_request()
assert client.get(f"/api/pass/{waiting_visit['reference']}", headers=KEY).status_code == 404
unknown_answer = client.get("/api/pass/VR-99999", headers=KEY).get_json()
hidden_answer = client.get(f"/api/pass/{waiting_visit['reference']}", headers=KEY).get_json()
assert unknown_answer == hidden_answer, "the same answer, so a reference tells nothing"
# On WhatsApp, a guard who is not an approver of it gets the same answer.
guard_only = client.post("/api/admin/guards", headers=ADMIN,
                         json={"name": "Lookup Guard", "phone": "+919300000020"}).get_json()
assert say("919300000020", waiting_visit["reference"]).startswith("No pass has code")
assert waiting_visit["name"] in say("919300000020", on_board_visit["reference"])
limits.forget_hits()
lookups = [client.get(f"/api/pass/{on_board_visit['reference']}", headers=KEY).status_code
           for _ in range(gate_routes.LOOKUPS_PER_MINUTE + 1)]
assert lookups[-1] == 429 and lookups.count(200) == gate_routes.LOOKUPS_PER_MINUTE, lookups
limits.forget_hits()
print("  board visits only, the same 404 for the rest, 60 lookups a minute per guard")

print("webhooks: every message in a payload, none without an id, logs hide secrets")
limits.forget_hits()
batch_one, batch_two = new_request(), new_request()
one_message = inbound(APPROVER, f"YES {batch_one['reference']}")["entry"][0]["changes"][0]
two_message = inbound(APPROVER, f"NO {batch_two['reference']}")["entry"][0]["changes"][0]
# Meta can send two entries, each with a change, in one payload. Both act.
client.post("/webhook/whatsapp", json={"entry": [{"changes": [one_message]},
                                                  {"changes": [two_message]}]})
assert visits.get(batch_one["reference"])["status"] == "approved"
assert visits.get(batch_two["reference"])["status"] == "declined"
# The same message twice in one payload acts once, and a message with no id is left out.
repeat_visit = new_request()
twice = inbound(APPROVER, f"YES {repeat_visit['reference']}")
twice["entry"][0]["changes"][0]["value"]["messages"] *= 2
sent_count = len(sent)
client.post("/webhook/whatsapp", json=twice)
to_approver = [body for to, body in sent[sent_count:]
               if whatsapp.same_number(to, APPROVER) and repeat_visit["reference"] in body]
assert len(to_approver) == 1, to_approver
assert visits.get(repeat_visit["reference"])["status"] == "approved"
no_id_visit = new_request()
nameless = inbound(APPROVER, f"YES {no_id_visit['reference']}")
del nameless["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
sent_count = len(sent)
client.post("/webhook/whatsapp", json=nameless)
assert visits.get(no_id_visit["reference"])["status"] == "pending" and len(sent) == sent_count
assert whatsapp.read_messages({"entry": [{"changes": [{"value": {}}]}]}) == []
assert whatsapp.read_messages({"entry": "nonsense"}) == []
# Access log lines hide a visitor's link and the pass and staff codes.
hidden_line = redaction.redact('"GET /api/visit/abc_DEF-123 HTTP/1.1"')
assert hidden_line == '"GET /api/visit/<hidden> HTTP/1.1"'
assert redaction.redact("/api/pass/KT-4821/entry") == "/api/pass/<hidden>/entry"
assert redaction.redact("/api/staff/1234567") == "/api/staff/<hidden>"
assert redaction.redact("/api/admin/visits?status=all") == "/api/admin/visits?status=all"
try:
    gunicorn_settings = runpy.run_path("gunicorn.conf.py")
except ImportError:  # gunicorn runs only on Linux, as on Render and GitHub
    gunicorn_settings = None
if gunicorn_settings is not None:
    assert gunicorn_settings["logger_class"].__name__ == "RedactingLogger"
# Many new addresses within the hour cannot grow the limit table past its hard size.
limits.forget_hits()
limits.add_silent_callers(limits.HARD_MAX_CALLERS + 5, 60)
limits.too_many("request", 1, 3600, who="one more")
assert limits.hit_buckets() <= limits.MAX_CALLERS + 1, limits.hit_buckets()
limits.forget_hits()
# The whole campus has a request cap, whatever the address.
real_cap = config.REQUESTS_PER_HOUR_ALL
config.REQUESTS_PER_HOUR_ALL = 2
try:
    capped = [client.post("/api/requests", json=payload) for _ in range(3)]
finally:
    config.REQUESTS_PER_HOUR_ALL = real_cap
    limits.forget_hits()
assert [c.status_code for c in capped] == [201, 201, 429]
assert "Call the gate desk" in capped[2].get_json()["error"]
print("  batched and repeated messages, no-id refused, redacted paths, bounded limits, a cap")

print("eleven guests are refused, not cut to ten")
limits.forget_hits()
crowd = client.post("/api/requests", json={**payload, "guests": [f"Guest {n}" for n in range(11)]})
assert crowd.status_code == 400 and "Up to 10" in crowd.get_json()["error"], crowd.get_json()
assert client.post("/api/requests", json={**payload, "guests": [f"G {n}" for n in range(10)]}
                   ).status_code == 201
print("  11 refused with the limit named, 10 accepted")

print("the database refuses a status it does not know, and the purge reads by key")
checked_visit = new_request()
for bad_sql in ("UPDATE visits SET status = 'lost' WHERE reference = %s",
                "UPDATE visits SET decided_by = 'someone' WHERE reference = %s"):
    try:
        with db.connect() as conn:
            conn.execute(bad_sql, (checked_visit["reference"],))
        raise AssertionError(f"the database took: {bad_sql}")
    except psycopg.errors.CheckViolation:
        pass
assert visits.get(checked_visit["reference"])["status"] == "pending"
# A visit past retention goes with its codes and photo; the rest stay.
with db.connect() as conn:
    conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                 (db.ago(config.RETAIN_DAYS + 1), checked_visit["reference"]))
db.forget_cache()
kept_count = visits.status_counts()
with db.connect() as conn:
    old_count = conn.execute("SELECT COUNT(*) AS n FROM visits WHERE created_at < %s",
                             (db.ago(config.RETAIN_DAYS),)).fetchone()["n"]
assert old_count >= 1
assert visits.purge_old() == old_count
assert visits.get(checked_visit["reference"]) is None
assert visits.codes_of(checked_visit["reference"]) == {}
assert sum(visits.status_counts().values()) == sum(kept_count.values()) - old_count
assert visits.purge_old() == 0, "nothing old, nothing deleted"
assert visits.next_due() is not None
print("  CHECK on status and decider, purge by reference, next_due on the status index")

print("odd bodies, NUL bytes and SQL text are refused, never a crash")
both_keys = {**ADMIN, **KEY}
for rule in application.app.url_map.iter_rules():
    if "POST" not in rule.methods:
        continue
    url = rule.rule
    for part in rule.arguments:
        url = url.replace(f"<{part}>", {"which": "gate", "action": "entry"}.get(part, "AB-1234"))
    for body in (b"[1]", b'"text"', b"5", b"true"):
        answer = client.post(url, data=body, headers={**both_keys,
                                                      "Content-Type": "application/json"})
        assert answer.status_code < 500, (url, body, answer.status_code)
    limits.forget_hits()
for url in ("/api/visit/%00", "/api/pass/A%00", "/api/admin/visits?q=%00",
            "/api/admin/visits?after=%00|x", "/api/admin/photo/%00"):
    assert client.get(url, headers=both_keys).status_code == 400, url
for url, body in (("/api/admin/staff/remove", {"code": "\x00"}),
                  ("/api/admin/offices/remove", {"name": "\x00"}),
                  ("/api/admin/decide", {"decision": "approve", "references": ["\x00"]})):
    assert client.post(url, json=body, headers=ADMIN).status_code == 400, url
# A bad reference stops the whole list first, so no approval goes without its log line.
half = new_request()
assert client.post("/api/admin/decide", headers=ADMIN, json={
    "decision": "approve", "references": [half["reference"], "\x00"]}).status_code == 400
assert visits.get(half["reference"])["status"] == "pending"
limits.forget_hits()
# Every value reaches SQL as a parameter, so SQL text is only text.
db.forget_cache()
stored = sum(visits.status_counts().values())
for text in ("YES VR-1' OR '1'='1", "IN KT-1234'; DELETE FROM visits;--",
             "'; DROP TABLE visits;--"):
    say(APPROVER, text)
injected = client.get("/api/admin/visits?q=' OR 1=1--", headers=ADMIN).get_json()
assert injected["visits"] == [], "the search matches the text, not every row"
db.forget_cache()
assert sum(visits.status_counts().values()) == stored
limits.forget_hits()
print("  a list, text or number body, NUL in a path, query or field, SQL in WhatsApp and search")

# Last, because it closes the database for the rest of this process.

finish()

"""Writes docs/whatsapp-messages.md: every WhatsApp message the app sends, scenario by scenario.

It drives the real app with WhatsApp captured, so the list always matches the code. It also
checks that each message fits in one WhatsApp message, and that no guard notice holds a code.

Run from the app folder: .venv\\Scripts\\python.exe tools\\whatsapp_messages.py"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import testdb

os.environ.update(
    META_TOKEN="fake-token", META_PHONE_NUMBER_ID="100000000000000", META_VERIFY_TOKEN="fake",
    META_APP_SECRET="", ALLOW_UNSIGNED_WEBHOOK="true",
    MAIN_APPROVER="+919000000001", BACKUP_APPROVER="+919000000002", GUARD="+919000000003",
    ADMIN_PHONE="+919000000004", GATE_KEY="demo-gate-key-long-enough",
    ADMIN_KEY="demo-admin-key-long-enough", GATE_DESK_PHONE="+912200000000",
    ESCALATE_MINUTES="15", APPROVERS="", AUTO_APPROVE_MINUTES="30", DATABASE_URL=testdb.url(),
)

import app as application
from core import config, db, limits
from models import people, visits
from services import timer, whatsapp

OUT = Path(__file__).resolve().parent.parent / "docs" / "whatsapp-messages.md"
ADMIN = {"X-Admin-Key": "demo-admin-key-long-enough"}
GATE = {"X-Gate-Key": "demo-gate-key-long-enough"}
APPROVER, BACKUP, DESK, ADMIN_PHONE = "919000000001", "919000000002", "919000000003", "919000000004"
GUARD, STAFF, OTHER = "+919000000005", "+919000000006", "+919000000007"
WHO = {"+919000000001": "the approver", "+919000000002": "the backup approver",
       "+919000000003": "the gate desk", "+919000000004": "the main admin",
       GUARD: "a guard", STAFF: "the staff member", OTHER: "an office approver"}

# The approval template's body, as setup.md gives it, so a template reads as WhatsApp shows it.
TEMPLATE = ("Campus visit request {0}.\n{1}\n\nName: {2}\nPhone: {3}\nAddress: {4}\nReason: {5}\n"
            "Visiting: {6}\nWith: {7}\n\nReply YES or NO followed by the reference to decide"
            " this request.")
STAFF_TEMPLATE = ("Campus entry recorded for {0} at {1} by {2}.\n\nIf this was not you, tell the"
                  " campus admin.")

sent = []


def capture_text(to, body):
    sent.append((to, body))


def capture_template(to, values, name=None):
    form = STAFF_TEMPLATE if name else TEMPLATE
    sent.append((to, form.format(*values) + f"\n\n(template {name or config.REQUEST_TEMPLATE})"))


whatsapp.send = capture_text
whatsapp.send_template = capture_template
client = application.app.test_client()
ids = iter(range(1, 10_000))


def say(sender, text):
    client.post("/webhook/whatsapp", json={"entry": [{"changes": [{"value": {"messages": [
        {"id": f"wamid.{next(ids)}", "from": sender, "type": "text", "text": {"body": text}}]}}]}]})


def photo(sender):
    client.post("/webhook/whatsapp", json={"entry": [{"changes": [{"value": {"messages": [
        {"id": f"wamid.{next(ids)}", "from": sender, "type": "image",
         "image": {"id": f"media.{next(ids)}"}}]}}]}]})


def request(**fields):
    body = {"name": "Asha Rao", "phone": "9876543210", "address": "Karjat", "reason": "Event",
            "visiting": "Annual fest", "guests": ["Ravi Rao"], **fields}
    return client.post("/api/requests", json=body).get_json()


def approved(**fields):
    visit = request(**fields)
    say(APPROVER, f"YES {visit['reference']}")
    return visit


def codes(visit):
    return visits.codes_of(visit["reference"])


def older(visit, hours):
    with db.connect() as conn:
        conn.execute("UPDATE visits SET created_at = %s WHERE reference = %s",
                     (db.ago(hours / 24), visit["reference"]))
    db.forget_cache()


def clear_entries():
    """Forgets the allow list entries, so the next code is not a repeat."""
    with db.connect() as conn:
        conn.execute("DELETE FROM staff_entries")


def later():
    """Moves the allow list entries 3 minutes back, past the repeat window, still today."""
    with db.connect() as conn:
        conn.execute("UPDATE staff_entries SET entered_at = %s", (db.ago(3 / 1440),))


sections = []
problems = []


def scenario(title, action, sender=None, text=None):
    """Runs one step and keeps every message it sent."""
    limits.forget_hits()
    sent.clear()
    action()
    messages = list(sent)
    for to, body in messages:
        if len(body) > 4096:
            problems.append(f"{title}: {len(body)} characters to {to}")
    sections.append((title, sender, text, messages))
    return messages


def main():
    db.init()
    client.post("/api/admin/guards", headers=ADMIN, json={"name": "Ravi", "phone": GUARD})
    client.post("/api/admin/offices", headers=ADMIN,
                json={"name": "Accounts", "main": OTHER, "backup": "", "tag": "Main Building"})
    dev = client.post("/api/admin/staff", headers=ADMIN,
                      json={"name": "Dr Anita Rao", "phone": STAFF, "tag": "Physics"}).get_json()

    # --- Approvers
    first = {}
    scenario("A visitor sends a request", lambda: first.update(request()))
    late = request()
    older(late, 0.5)
    scenario("Nobody answers in time: the backup approver is asked", timer.escalate_due)
    office = request(reason="See an office", visiting="x", office="Accounts")
    older(office, 0.5)
    scenario("An office with no backup: its approver gets a reminder", timer.escalate_due)
    old_pair = people.approver_table()["reasons"]["Delivery"]
    request(reason="Delivery", visiting="Front office")
    scenario("An admin changes the approver: open requests go to the new one",
             lambda: client.post("/api/admin/approvers", headers=ADMIN, json={
                 "reason": "Delivery", "main": "+919000000077", "backup": ""}))
    client.post("/api/admin/approvers", headers=ADMIN,
                json={"reason": "Delivery", "main": old_pair[0], "backup": old_pair[1]})
    auto = request()
    with db.connect() as conn:
        conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                     ("2020-01-01T00:00:00+00:00", auto["reference"]))
    db.forget_cache()
    scenario("Nobody answers in working hours: the app approves by itself",
             timer.auto_approve_due)
    ref = first["reference"]
    scenario("The approver replies YES", lambda: say(APPROVER, f"yes {ref.lower()}"),
             APPROVER, f"yes {ref.lower()}")
    scenario("A second YES on the same request", lambda: say(APPROVER, f"YES {ref}"),
             APPROVER, f"YES {ref}")
    declined = request()
    scenario("The approver replies NO", lambda: say(APPROVER, f"No, {declined['reference']}."),
             APPROVER, f"No, {declined['reference']}.")
    scenario("A reference with a typing mistake", lambda: say(APPROVER, "YES VR-12"),
             APPROVER, "YES VR-12")
    scenario("An approver decides another reason's request",
             lambda: say(OTHER[1:], f"YES {late['reference']}"), OTHER[1:],
             f"YES {late['reference']}")
    expired = request()
    older(expired, config.PASS_HOURS + 1)
    scenario("YES on a request older than the pass time",
             lambda: say(APPROVER, f"YES {expired['reference']}"), APPROVER,
             f"YES {expired['reference']}")
    request(name="Neha Joshi")
    request(name="Karan Mehta")
    scenario("YES with no reference while several wait", lambda: say(APPROVER, "YES"),
             APPROVER, "YES")
    scenario("Any other message from an approver", lambda: say(APPROVER, "hello"),
             APPROVER, "hello")
    for other in visits.open_requests():
        visits.decide(other["reference"], db.DECLINED, db.BY_MAIN)
    racing = request(phone="9123456781")
    with db.connect() as conn:
        conn.execute("INSERT INTO blacklist (number_key, phone_key, phone, name, reason, added_at)"
                     " VALUES ('919123456781', '9123456781', '9123456781', 'X', '', %s)",
                     (db.now(),))
    db.forget_cache()
    scenario("YES on a request whose number was just blacklisted",
             lambda: say(APPROVER, f"YES {racing['reference']}"), APPROVER,
             f"YES {racing['reference']}")
    visits.decide(racing["reference"], db.DECLINED, db.BY_MAIN)
    scenario("YES with nothing waiting", lambda: say(APPROVER, "YES"), APPROVER, "YES")

    # --- Guards and visitors at the gate
    visit = approved()
    entry, leave = codes(visit)["entry"], codes(visit)["exit"]
    scenario("A guard looks up a pass by its entry code", lambda: say(GUARD[1:], entry),
             GUARD[1:], entry)
    scenario("IN with no code", lambda: say(GUARD[1:], "IN"), GUARD[1:], "IN")
    scenario("IN with the exit code", lambda: say(GUARD[1:], f"IN {leave}"), GUARD[1:],
             f"IN {leave}")
    scenario("IN with the entry code", lambda: say(GUARD[1:], f"in {entry}"), GUARD[1:],
             f"in {entry}")
    scenario("The guard sends the photo", lambda: photo(GUARD[1:]), GUARD[1:], "(a photo)")
    scenario("A photo with no IN before it", lambda: photo(GUARD[1:]), GUARD[1:], "(a photo)")
    owed_first, owed_second = codes(approved()), codes(approved())
    say(GUARD[1:], f"IN {owed_first['entry']}")
    scenario("IN for a second visitor while a photo is still owed",
             lambda: say(GUARD[1:], f"IN {owed_second['entry']}"), GUARD[1:],
             f"IN {owed_second['entry']}")
    scenario("CANCEL drops the photo still owed", lambda: say(GUARD[1:], "CANCEL"), GUARD[1:],
             "CANCEL")
    scenario("IN again for a visitor inside", lambda: say(GUARD[1:], f"IN {entry}"), GUARD[1:],
             f"IN {entry}")
    scenario("OUT with the exit code", lambda: say(GUARD[1:], f"OUT {leave}"), GUARD[1:],
             f"OUT {leave}")
    scenario("OUT again on a closed pass", lambda: say(GUARD[1:], f"OUT {leave}"), GUARD[1:],
             f"OUT {leave}")
    waiting = request()
    scenario("IN for a pass not approved yet",
             lambda: say(GUARD[1:], f"IN {codes(waiting)['entry']}"), GUARD[1:], "IN <entry code>")
    gone = approved()
    older(gone, config.PASS_HOURS + 1)
    scenario("IN for an expired pass", lambda: say(GUARD[1:], f"IN {codes(gone)['entry']}"),
             GUARD[1:], "IN <entry code>")
    banned = approved(phone="9123456782")
    client.post("/api/admin/blacklist", headers=ADMIN,
                json={"name": "Kiran", "phone": "9123456782", "reason": ""})
    scenario("IN for a pass whose number is on the blacklist",
             lambda: say(GUARD[1:], f"IN {codes(banned)['entry']}"), GUARD[1:], "IN <entry code>")

    # --- The allow list
    code = dev["code"]
    scenario("A guard sends an allow list code", lambda: say(GUARD[1:], code), GUARD[1:], code)
    scenario("The same code again within 2 minutes", lambda: say(GUARD[1:], f"IN {code}"),
             GUARD[1:], f"IN {code}")
    later()
    scenario("The same code later that day: the exit", lambda: say(GUARD[1:], code),
             GUARD[1:], code)
    later()
    say(GUARD[1:], code)  # back in, so OUT below corrects an entry
    later()
    scenario("OUT with an allow list code, to correct a wrong scan",
             lambda: say(GUARD[1:], f"OUT {code}"), GUARD[1:], f"OUT {code}")
    scenario("An allow list code nobody has", lambda: say(GUARD[1:], "1000000"), GUARD[1:],
             "1000000")
    clear_entries()
    config.STAFF_ENTRY_TEMPLATE = "staff_entry"
    scenario("An allow list code, with the staff_entry template set",
             lambda: say(GUARD[1:], code), GUARD[1:], code)
    config.STAFF_ENTRY_TEMPLATE = ""
    blocked = client.post("/api/admin/staff", headers=ADMIN,
                          json={"name": "Mohan", "phone": "+919123456783"}).get_json()["code"]
    client.post("/api/admin/blacklist", headers=ADMIN,
                json={"name": "Mohan", "phone": "9123456783", "reason": ""})
    scenario("An allow list code whose number is on the blacklist",
             lambda: say(GUARD[1:], blocked), GUARD[1:], blocked)
    clear_entries()
    scenario("A staff entry recorded on the gate page",
             lambda: client.post(f"/api/staff/{code}/scan", headers=GATE))
    later()
    scenario("A staff exit recorded on the gate page: no message",
             lambda: client.post(f"/api/staff/{code}/scan", headers=GATE))

    # --- Bulk approval and keys
    many = [request(name=name) for name in ("Neha Joshi", "Karan Mehta", "Isha Rao")]
    scenario("A super admin approves three requests at once",
             lambda: client.post("/api/admin/decide", headers=ADMIN, json={
                 "references": [v["reference"] for v in many], "decision": "approve"}))
    scenario("KEY from the gate desk number", lambda: say(DESK, "KEY"), DESK, "KEY")
    scenario("KEY from the main admin's number", lambda: say(ADMIN_PHONE, "KEY"), ADMIN_PHONE,
             "KEY")
    scenario("KEY from an added guard", lambda: say(GUARD[1:], "KEY"), GUARD[1:], "KEY")

    # --- Help for each mix of jobs
    scenario("Help for a guard", lambda: say(GUARD[1:], "hello"), GUARD[1:], "hello")
    scenario("Help for the main admin", lambda: say(ADMIN_PHONE, "hello"), ADMIN_PHONE, "hello")
    scenario("A number that is no approver, guard or admin", lambda: say("919999999999", "hi"),
             "919999999999", "hi")

    # A message the app sends by itself never holds a gate code. A reply may repeat a code the
    # guard typed, which the guard already has.
    with db.connect() as conn:
        all_codes = [row["code"] for row in conn.execute("SELECT code FROM gate_codes")]
    for title, sender, _, messages in sections:
        for to, body in messages:
            if sender is None and any(code in body for code in all_codes):
                problems.append(f"{title}: a gate code in the message to {to}")
    write()
    db.close()
    if problems:
        sys.exit("Problems:\n" + "\n".join(problems))
    print("Wrote", OUT)


def tidy(text):
    """Keys are secret, so the page shows a placeholder for each."""
    return re.sub(r"(key for the visitor access app is:\n)\S+", r"\1<the key>", text)


def write():
    lines = [
        "# WhatsApp messages",
        "",
        "Every message the app sends on WhatsApp, in each scenario. A tool made this page by",
        "running the app with WhatsApp captured, so the words are exactly what people get.",
        "To make it again after a change, run `tools\\whatsapp_messages.py`, see",
        "[maintenance.md](maintenance.md). Keys show as `<the key>`.",
        "",
        "Approval requests and, once it is approved, the staff entry message go out as Meta",
        "templates, which arrive at any time. Every other message is plain text, which arrives",
        "only if the person wrote to the app's number in the last 24 hours. A reply always",
        "arrives, because the person just wrote.",
        "",
    ]
    for title, sender, text, messages in sections:
        lines += [f"## {title}", ""]
        if sender:
            who = WHO.get("+" + sender, "someone")
            lines += [f"{who[0].upper()}{who[1:]} sends: `{text}`", ""]
        if not messages:
            lines += ["The app sends nothing.", ""]
        for to, body in messages:
            lines += [f"To {WHO.get('+' + whatsapp.digits(to), to)}:", "", "```",
                      tidy(body), "```", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

"""Sends the approval request over WhatsApp and reads the replies."""

import re
from datetime import datetime

import requests

import config
import db

API_URL = f"https://graph.facebook.com/v21.0/{config.META_PHONE_NUMBER_ID}/messages"
TIMEOUT_SECONDS = 15

# VR-40221, or VR-4022 from before five digits. Also typed as VR40221, VR 40221 or 40221.
CODE = re.compile(r"^(?:VR-?)?(\d{4,5})$", re.IGNORECASE)
# An entry or exit code, as KT-4821. A guard may type kt4821 or KT 4821.
GATE_CODE = re.compile(r"^([A-HJ-NP-Z]{2})-?(\d{4})$")

# One phone number can be approver and guard, so each job has its own word.
DECIDE_WORDS = {"YES": db.APPROVED, "NO": db.DECLINED}
GATE_WORDS = {"IN": db.ENTRY, "OUT": db.EXIT}
# The gate desk or admin number gets its key back.
KEY_WORD = "KEY"

HELP = (
    "Send a reference like VR-40221, or a pass code like KT-4821, to look it up.\n"
    "YES <reference> approves. NO <reference> declines.\n"
    "IN <entry code>, then a photo of the visitor, records entry.\n"
    "OUT <exit code> records exit.\n"
    "The entry code and the exit code are on the visitor's pass."
)
EXAMPLES = {db.ENTRY: "IN KT-4821", db.EXIT: "OUT RM-0937"}


def digits(phone):
    """Digits only, as Meta sends them, so +91 98765 43210 in a setting still matches."""
    return "".join(c for c in phone if c.isdigit())


def same_number(a, b):
    return digits(a) == digits(b)


def _post(to_phone, message):
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {config.META_TOKEN}"},
        json={"messaging_product": "whatsapp", "to": digits(to_phone), **message},
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(
            f"WhatsApp send failed ({response.status_code}): {response.text}"
        )
    return response.json()


def token_works():
    """True when Meta accepts the token for this phone number. Sends nothing."""
    try:
        response = requests.get(
            f"https://graph.facebook.com/v21.0/{config.META_PHONE_NUMBER_ID}",
            params={"fields": "id"},
            headers={"Authorization": f"Bearer {config.META_TOKEN}"},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return False
    return response.ok


def send(to_phone, body):
    """Plain text. Arrives only within 24 hours of the person's last message."""
    return _post(to_phone, {"type": "text", "text": {"body": body}})


def send_template(to_phone, values):
    """The approved template, which arrives at any time."""
    return _post(to_phone, {
        "type": "template",
        "template": {
            "name": config.REQUEST_TEMPLATE,
            "language": {"code": config.TEMPLATE_LANGUAGE},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": value} for value in values],
            }],
        },
    })


# The visit_request template's {{1}} to {{8}}: reference, who is asked, six details.
def template_values(visit, escalated=False):
    return [
        visit["reference"],
        "Backup approver: no answer from the first approver."
        if escalated
        else "New request, waiting for your decision.",
        visit["name"],
        visit["phone"],
        visit["address"],
        visit["reason"],
        visit["visiting"],
        # Meta refuses an empty value, so no guests is said in words.
        ", ".join(visit["guests"]) or "No one",
    ]


def request_body(visit, escalated=False):
    lines = [
        "Backup approver: no answer from the first approver."
        if escalated
        else "New campus visit request.",
        "",
        f"Reference: {visit['reference']}",
        f"Name: {visit['name']}",
        f"Phone: {visit['phone']}",
        f"Address: {visit['address']}",
        f"Reason: {visit['reason']}",
        f"Visiting: {visit['visiting']}",
    ]
    if visit["guests"]:
        lines.append(f"With: {', '.join(visit['guests'])}")
    lines += [
        "",
        f"Reply YES {visit['reference']} to approve.",
        f"Reply NO {visit['reference']} to decline.",
    ]
    return "\n".join(lines)


def brief(visit):
    """One line naming who is asking and why."""
    return (
        f"{visit['reference']}: {visit['name']}, visiting {visit['visiting']}"
        f" ({visit['reason']})"
    )


def waiting_body(visits):
    """What to send an approver who has not given a usable decision."""
    if not visits:
        return f"No request is waiting for a decision.\n\n{HELP}"
    if len(visits) == 1:
        return request_body(visits[0])
    lines = ["These requests are waiting for you:", ""]
    lines += [brief(v) for v in visits]
    lines += ["", "Reply YES <reference> or NO <reference>."]
    return "\n".join(lines)


GATE_LINES = {
    db.PENDING: "Not approved yet. Do not let them in.",
    db.ESCALATED: "Not approved yet. Do not let them in.",
    db.DECLINED: "Declined. Do not let them in.",
    db.APPROVED: "Approved. Reply IN and the entry code on the visitor's pass,"
                 " then send a photo of the visitor.",
    db.INSIDE: "Inside now. Reply OUT and the exit code on the visitor's pass"
               " to record the exit.",
    db.CLOSED: "Closed. The visit is over and its codes are finished.",
    db.EXPIRED: "Expired. Do not let them in. They must send a new request.",
}
# A reply repeats only a code the sender typed, so an approver never learns a gate code.
NEXT_STEP = {
    (db.APPROVED, db.ENTRY): "Approved. Reply IN {code}, then send a photo of the visitor.",
    (db.INSIDE, db.EXIT): "Inside now. Reply OUT {code} to record the exit.",
}


def local_time(stamp):
    """A stored UTC time on the campus clock, as 6 Oct, 10:16."""
    moment = datetime.fromisoformat(stamp).astimezone(config.WORK_TIMEZONE)
    return f"{moment.day} {moment:%b}, {moment:%H:%M}"


def gate_line(visit, code=None, kind=None):
    line = NEXT_STEP.get((visit["status"], kind))
    return line.format(code=code) if line else GATE_LINES[visit["status"]]


def pass_body(visit, code=None, kind=None):
    """The reply to a reference or pass code. A closed visit shows only its times."""
    if visit["status"] == db.CLOSED:
        lines = [
            gate_line(visit),
            "",
            f"Reference: {visit['reference']}",
            f"Entered: {local_time(visit['entered_at'])}",
            f"Exited: {local_time(visit['exited_at'])}",
        ]
        return "\n".join(lines)

    lines = [
        gate_line(visit, code, kind),
        "",
        f"Reference: {visit['reference']}",
        f"Name: {visit['name']}",
        f"Phone: {visit['phone']}",
        f"Visiting: {visit['visiting']}",
        f"Reason: {visit['reason']}",
    ]
    if visit["guests"]:
        lines.append(f"With: {', '.join(visit['guests'])}")
    if visit["entered_at"]:
        lines.append(f"Entered: {local_time(visit['entered_at'])}")
    if visit["exited_at"]:
        lines.append(f"Exited: {local_time(visit['exited_at'])}")
    return "\n".join(lines)


def photo_request(visit, code):
    """What the guard reads after IN, while the visitor waits at the gate."""
    return (
        f"Take a photo of {visit['name']} and send it here.\n"
        f"{code} is let in once the photo arrives."
    )


def normalize_reference(text):
    found = CODE.match(text.strip())
    return f"VR-{found.group(1)}" if found else None


def normalize_gate_code(text):
    """KT-4821 from kt4821, KT 4821 or kt-4821. None for anything else."""
    found = GATE_CODE.match("".join(text.split()).upper())
    if not found or found.group(1) == "VR":
        return None
    return f"{found.group(1)}-{found.group(2)}"


def first_code(words, normalize):
    """The code after YES, NO, IN or OUT, or None. Tries all words joined, then two, then one."""
    for count in (len(words), 2, 1):
        found = normalize("".join(words[:count]))
        if found:
            return found
    return None


def read_reply(body):
    """(kind, value, key), kind being decide, gate, lookup, key or help."""
    parts = body.strip().split()
    if not parts:
        return "help", None, None

    word = parts[0].upper()

    if word == KEY_WORD and len(parts) == 1:
        return "key", None, None
    # A code may come with a space in it, as KT 4821, so the rest is joined.
    rest = "".join(parts[1:])
    if word in DECIDE_WORDS:
        # An unreadable reference goes on as typed. It must never decide the one request waiting.
        key = first_code(parts[1:], normalize_reference)
        return "decide", DECIDE_WORDS[word], key or rest.upper() or None
    if word in GATE_WORDS:
        # Whatever was typed goes on, so a wrong code is named in the reply.
        key = first_code(parts[1:], normalize_gate_code)
        return "gate", GATE_WORDS[word], key or rest.upper() or None

    whole = "".join(parts)
    key = normalize_reference(whole) or normalize_gate_code(whole)
    if key:
        return "lookup", None, key
    return "help", None, None


def read_incoming(payload):
    """(message_id, sender, text, photo media id) from a Meta webhook, or four Nones."""
    nothing = None, None, None, None
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
        kind = message.get("type")
        if kind == "text":
            return message.get("id"), message["from"], message["text"]["body"], None
        if kind == "image":
            image = message["image"]
            return message.get("id"), message["from"], image.get("caption", ""), image["id"]
        return nothing
    except (KeyError, IndexError, TypeError):
        return nothing


def read_failures(payload):
    """Undelivered messages as (recipient, code, reason). The only sign of the 24-hour rule."""
    failures = []
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for status in change.get("value", {}).get("statuses", []):
                    if status.get("status") != "failed":
                        continue
                    for error in status.get("errors") or [{}]:
                        failures.append((
                            status.get("recipient_id", "?"),
                            error.get("code", "?"),
                            error.get("title") or error.get("message") or "no reason given",
                        ))
    except (AttributeError, TypeError):
        pass
    return failures


def notify(phone, visit, escalated=False):
    """Send the approval request. Returns why the template failed if TEMPLATE_FALLBACK sent text."""
    if not config.REQUEST_TEMPLATE:
        send(phone, request_body(visit, escalated))
        return None
    try:
        send_template(phone, template_values(visit, escalated))
        return None
    except RuntimeError as failure:
        if not config.TEMPLATE_FALLBACK:
            raise
        problem = str(failure)
    send(phone, request_body(visit, escalated))
    return problem


def notify_approver(visit, approvers):
    """approvers is the visit's (main, backup)."""
    return notify(approvers[0], visit)


def notify_backup(visit, approvers):
    return notify(approvers[1], visit, escalated=True)


def auto_approved_body(visit, minutes):
    return (f"{visit['reference']} was approved automatically. No one answered within"
            f" {minutes} minutes of the request, made in working hours.\n\n{brief(visit)}")


def guard_update_body(visit):
    """What each guard reads when a visitor is approved. Never a gate code."""
    lines = [f"Approved visitor on the way. {brief(visit)}"]
    if visit["guests"]:
        lines.append(f"With: {', '.join(visit['guests'])}")
    lines += ["", "When they arrive, send IN and the entry code on their pass,"
                  " then a photo of the visitor."]
    return "\n".join(lines)


def key_body(name, key):
    return (f"The {name} key for the visitor access app is:\n{key}\n\n"
            "Do not share it outside the people who need it.")


def own_key_body(key):
    return (f"Your own gate key for the visitor access app is:\n{key}\n\n"
            "Your old key no longer works. Do not share this one.")

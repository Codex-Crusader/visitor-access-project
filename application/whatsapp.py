"""Sends the approval request over WhatsApp and reads the replies."""

import re
from datetime import datetime

import requests

import config
import db
import staff

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
CANCEL_WORD = "CANCEL"

# The help each person gets names only the jobs they have. One number can have all three.
HELP_LINES = {
    "approver": [
        "Send a reference like VR-40221 to see that request.",
        "YES <reference> approves. NO <reference> declines. Small letters work too.",
    ],
    "guard": [
        "Send a pass code like KT-4821 to see that pass.",
        "IN <entry code>, then a photo of the visitor, records entry.",
        "OUT <exit code> records exit. Both codes are on the visitor's pass.",
        "A staff member's 7-digit allow list code records their entry at once.",
        "CANCEL drops the photo you still owe after IN.",
    ],
}
KEY_LINES = {
    frozenset({"guard"}): "KEY sends you your key for the gate page.",
    frozenset({"admin"}): "KEY sends you your key for the admin page.",
    frozenset({"guard", "admin"}): "KEY sends you your keys for the gate page and the admin page.",
}
ROLES = ("approver", "guard", "admin")


def help_text(roles):
    """The commands for these roles, in one message."""
    lines = []
    if "approver" in roles:
        lines += HELP_LINES["approver"]
    if "guard" in roles:
        lines += HELP_LINES["guard"]
    keys = frozenset(roles) & {"guard", "admin"}
    if keys:
        lines.append(KEY_LINES[keys])
    return "\n".join(lines)


HELP = help_text(ROLES)
EXAMPLES = {db.ENTRY: "IN KT-4821", db.EXIT: "OUT RM-0937"}


def digits(phone):
    """Digits only, as Meta sends them, so +91 98765 43210 in a setting still matches."""
    return "".join(c for c in phone if c.isdigit())


def same_number(a, b):
    return digits(a) == digits(b)


class Uncertain(RuntimeError):
    """Meta may have the message: no answer in time, or a fault on Meta's side."""


def _post(to_phone, message):
    try:
        response = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {config.META_TOKEN}"},
            json={"messaging_product": "whatsapp", "to": digits(to_phone), **message},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.ReadTimeout as lost:
        raise Uncertain(f"No answer from WhatsApp in {TIMEOUT_SECONDS} s") from lost
    if response.status_code >= 500:
        raise Uncertain(f"WhatsApp fault ({response.status_code}): {response.text}")
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


def send_template(to_phone, values, name=None):
    """An approved template, which arrives at any time. The approval request by default."""
    return _post(to_phone, {
        "type": "template",
        "template": {
            "name": name or config.REQUEST_TEMPLATE,
            "language": {"code": config.TEMPLATE_LANGUAGE},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": value} for value in values],
            }],
        },
    })


# The visit_request template's {{1}} to {{8}}: reference, who is asked, six details.
# The second line of the approval request, by stage. A reminder goes to an approver who is
# also their own backup: no second person to ask.
STAGE_LINES = {
    "new": "New request, waiting for your decision.",
    "backup": "Backup approver: no answer from the first approver.",
    "reminder": "Reminder: this request still waits for your decision.",
}


def template_values(visit, stage="new"):
    return [
        visit["reference"],
        STAGE_LINES[stage],
        visit["name"],
        visit["phone"],
        visit["address"],
        visit["reason"],
        visit["visiting"],
        # Meta refuses an empty value, so no guests is said in words.
        ", ".join(visit["guests"]) or "No one",
    ]


def request_body(visit, stage="new"):
    lines = [
        "New campus visit request." if stage == "new" else STAGE_LINES[stage],
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


def waiting_body(visits, help_lines=HELP):
    """What to send an approver who has not given a usable decision."""
    if not visits:
        return f"No request is waiting for you.\n\n{help_lines}"
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


def pass_body(visit, code=None, kind=None, phone=False):
    """The reply to a reference or pass code. A closed visit shows only its times.

    phone: for an approver, who has the number already. A guard decides without it."""
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
        *([f"Phone: {visit['phone']}"] if phone else []),
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


def photo_owed(visit):
    """The reply to a second IN while a photo is still owed. One photo, one visitor."""
    who = f"{visit['name']} ({visit['reference']})" if visit else "the last visitor"
    return (f"You still owe the photo of {who}. Send that photo first, so it cannot go to the"
            f" wrong visitor. To drop it, send {CANCEL_WORD}. Then send IN again.")


def photo_cancelled(visit):
    who = f"{visit['name']} ({visit['reference']})" if visit else "that pass"
    return (f"The photo of {who} is no longer waited for, and nobody was let in."
            " Send IN and the entry code to start again.")


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


# Each of these reads as a space in a reply.
PUNCTUATION = str.maketrans(dict.fromkeys(",.!?;:'\"()", " "))


def read_reply(body):
    """(kind, value, key). The kind is "decide", "gate", "staff", "lookup", "key", "cancel" or
    "help".

    Any case works: yes vr-40221 is YES VR-40221. Marks a phone adds, as in "No, VR-40221."
    or "Yes!", are dropped. The dash stays: it is part of a code."""
    parts = body.translate(PUNCTUATION).strip().split()
    if not parts:
        return "help", None, None

    word = parts[0].upper()

    if word == KEY_WORD and len(parts) == 1:
        return "key", None, None
    if word == CANCEL_WORD and len(parts) == 1:
        return "cancel", None, None
    # A code may come with a space in it, as KT 4821, so the rest is joined.
    rest = "".join(parts[1:])
    if word in DECIDE_WORDS:
        # An unreadable reference goes on as typed. It must never decide the one request waiting.
        key = first_code(parts[1:], normalize_reference)
        return "decide", DECIDE_WORDS[word], key or rest.upper() or None
    if word == "IN" and staff.normalize_code(rest):
        return "staff", None, rest
    if word in GATE_WORDS:
        # Whatever was typed goes on, so a wrong code is named in the reply.
        key = first_code(parts[1:], normalize_gate_code)
        return "gate", GATE_WORDS[word], key or rest.upper() or None

    whole = "".join(parts)
    if staff.normalize_code(whole):
        return "staff", None, whole
    key = normalize_reference(whole) or normalize_gate_code(whole)
    if key:
        return "lookup", None, key
    return "help", None, None


def read_messages(payload):
    """Each (message_id, sender, text, photo media id) in a Meta webhook. Meta can send several
    in one payload. A message with no id is left out: it could not be told from a repeat."""
    found = []
    try:
        changes = [change for entry in payload.get("entry", []) for change in entry["changes"]]
    except (KeyError, TypeError, AttributeError):
        return found
    for change in changes:
        try:
            messages = change["value"].get("messages", [])
        except (KeyError, TypeError, AttributeError):
            continue
        for message in messages:
            read = _read_message(message)
            if read is not None:
                found.append(read)
    return found


def _read_message(message):
    """One text or image message as a tuple, or None for any other kind or shape."""
    try:
        message_id, kind = message.get("id"), message.get("type")
        if not message_id:
            return None
        if kind == "text":
            return message_id, message["from"], message["text"]["body"], None
        if kind == "image":
            image = message["image"]
            return message_id, message["from"], image.get("caption", ""), image["id"]
    except (KeyError, TypeError, AttributeError):
        pass
    return None


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


def notify(phone, visit, stage="new"):
    """Send the approval request. Returns why the template failed if TEMPLATE_FALLBACK sent text."""
    if not config.REQUEST_TEMPLATE:
        send(phone, request_body(visit, stage))
        return None
    try:
        send_template(phone, template_values(visit, stage))
        return None
    except Uncertain:
        raise  # the template may have arrived: plain text too would ask twice
    except RuntimeError as failure:
        if not config.TEMPLATE_FALLBACK:
            raise
        problem = str(failure)
    send(phone, request_body(visit, stage))
    return problem


def notify_approver(visit, approvers):
    """approvers is the visit's (main, backup)."""
    return notify(approvers[0], visit)


def notify_backup(visit, approvers):
    """Ask the backup. An approver who is their own backup gets a reminder instead."""
    main, backup = approvers
    return notify(backup, visit, "reminder" if same_number(main, backup) else "backup")


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


# WhatsApp takes 4,096 characters in one message. The list stops well before that.
LIST_CHARACTERS = 3500


def guard_list_bodies(visits):
    """What each guard reads after approvals in bulk: one list, in as few messages as fit.
    Never a gate code."""
    head = f"{len(visits)} approved visitors on the way:"
    foot = ("When they arrive, send IN and the entry code on their pass,"
            " then a photo of each visitor.")
    bodies, lines = [], [head, ""]
    for visit in visits:
        line = brief(visit) + (f", with {', '.join(visit['guests'])}" if visit["guests"] else "")
        if sum(len(part) + 1 for part in lines) + len(line) > LIST_CHARACTERS:
            bodies.append("\n".join(lines))
            lines = ["More approved visitors:", ""]
        lines.append(line)
    bodies.append("\n".join([*lines, "", foot]))
    return bodies


def key_body(name, key):
    return (f"The {name} key for the visitor access app is:\n{key}\n\n"
            "Do not share it outside the people who need it.")


def own_key_body(key, which="gate"):
    return (f"Your own {which} key for the visitor access app is:\n{key}\n\n"
            "Your old key no longer works. Do not share this one.")


GUARD_NUMBER = re.compile(r"\s*\+\d+$")


def guard_name(by):
    """A guard's label with no number, as Ravi or Gate desk. Staff need no guard's phone."""
    return GUARD_NUMBER.sub("", by).replace(" (shared key)", "")


def staff_entry_values(person, stamp, by):
    """The allow list entry template's {{1}} to {{3}}: name, time, guard."""
    return [person["name"], local_time(stamp), guard_name(by)]


def staff_entry_body(person, stamp, by):
    """What a person on the allow list reads when a guard records their entry."""
    return (f"Campus entry recorded for {person['name']} at {local_time(stamp)}"
            f" by {guard_name(by)}.\n\nIf this was not you, tell the campus admin.")


def notify_staff_entry(person, stamp, by):
    """The template when STAFF_ENTRY_TEMPLATE is set, else plain text."""
    if config.STAFF_ENTRY_TEMPLATE:
        send_template(person["phone"], staff_entry_values(person, stamp, by),
                      config.STAFF_ENTRY_TEMPLATE)
    else:
        send(person["phone"], staff_entry_body(person, stamp, by))


def staff_entry_reply(person, stamp, new, told):
    """What the guard reads after an allow list code. The name lets the guard check the face."""
    if not new:
        return (f"Already recorded: {person['name']} entered at {local_time(stamp)}."
                " Nothing new was recorded or sent.")
    sent = ("A WhatsApp message about this entry was sent to them." if told
            else "The WhatsApp message to them could not be sent. The entry is recorded.")
    return (f"Entry recorded: {person['name']}, allow list code {person['code']},"
            f" at {local_time(stamp)}.\n"
            f"Check that this is {person['name']}. {sent}")

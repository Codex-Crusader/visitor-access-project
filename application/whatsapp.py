"""Sends the approval request over WhatsApp and reads the replies."""

import re

import requests

import config
import db

API_URL = f"https://graph.facebook.com/v21.0/{config.META_PHONE_NUMBER_ID}/messages"
TIMEOUT_SECONDS = 15

CODE = re.compile(r"^(?:VR-)?(\d{4})$", re.IGNORECASE)

# One phone number can be approver and guard, so each job has its own word.
DECIDE_WORDS = {"YES": db.APPROVED, "NO": db.DECLINED}
GATE_WORDS = {"IN": "entry", "OUT": "exit"}

HELP = (
    "Send a code like VR-4022 to look it up.\n"
    "YES <code> approves. NO <code> declines.\n"
    "IN <code> records entry. OUT <code> records exit."
)


def digits(phone):
    """Meta wants the number without a plus sign."""
    return phone.lstrip("+")


def same_number(a, b):
    return digits(a) == digits(b)


def send(to_phone, body):
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {config.META_TOKEN}"},
        json={
            "messaging_product": "whatsapp",
            "to": digits(to_phone),
            "type": "text",
            "text": {"body": body},
        },
        timeout=TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise RuntimeError(
            f"WhatsApp send failed ({response.status_code}): {response.text}"
        )
    return response.json()


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
    db.APPROVED: "Approved. Reply IN {ref} to record the entry.",
    db.INSIDE: "Inside now. Reply OUT {ref} to record the exit.",
    db.CLOSED: "Closed. The visit is over and this code is finished.",
}


def pass_body(visit):
    """What the guard sees after sending a code.

    A closed visit is over, so it answers with times and nothing personal.
    The same rule as the gate page and the pass endpoint.
    """
    if visit["status"] == db.CLOSED:
        lines = [
            GATE_LINES[db.CLOSED].format(ref=visit["reference"]),
            "",
            f"Reference: {visit['reference']}",
            f"Entered: {visit['entered_at']}",
            f"Exited: {visit['exited_at']}",
        ]
        return "\n".join(lines)

    lines = [
        GATE_LINES[visit["status"]].format(ref=visit["reference"]),
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
        lines.append(f"Entered: {visit['entered_at']}")
    if visit["exited_at"]:
        lines.append(f"Exited: {visit['exited_at']}")
    return "\n".join(lines)


def normalize_reference(text):
    found = CODE.match(text.strip())
    return f"VR-{found.group(1)}" if found else None


def read_reply(body):
    """Work out what the sender wants.

    Returns (kind, value, reference) where kind is one of:
    decide, gate, lookup, help.
    """
    parts = body.strip().split()
    if not parts:
        return "help", None, None

    word = parts[0].upper()
    rest = parts[1] if len(parts) > 1 else ""

    if word in DECIDE_WORDS:
        return "decide", DECIDE_WORDS[word], normalize_reference(rest)
    if word in GATE_WORDS:
        return "gate", GATE_WORDS[word], normalize_reference(rest)

    reference = normalize_reference(parts[0])
    if reference and len(parts) == 1:
        return "lookup", None, reference
    return "help", None, None


def read_incoming(payload):
    """Pull (message_id, sender, text) out of a Meta webhook payload."""
    try:
        value = payload["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
        if message.get("type") != "text":
            return None, None, None
        return message.get("id"), message["from"], message["text"]["body"]
    except (KeyError, IndexError, TypeError):
        return None, None, None


def notify_approver(visit):
    send(config.MAIN_APPROVER, request_body(visit))


def notify_backup(visit):
    send(config.BACKUP_APPROVER, request_body(visit, escalated=True))

"""The WhatsApp webhook: approvers decide, guards record entry and exit."""


import logging

from flask import Blueprint, request

import access
import config
import db
import entries
import notify
import people
import visits
import whatsapp
from routes import gate

# The same logger as app.logger, so every message reaches one place.
log = logging.getLogger("app")
bp = Blueprint("webhook", __name__)


# After IN <code>, the guard has this long to send the visitor's photo.
PHOTO_MINUTES = 10


@bp.get("/webhook/whatsapp")
def verify_webhook():
    """Meta calls this once to confirm the address belongs to us."""
    args = request.args
    if (
        args.get("hub.mode") == "subscribe"
        and args.get("hub.verify_token") == config.META_VERIFY_TOKEN
    ):
        return args.get("hub.challenge", ""), 200
    return "", 403


EXPIRED_REQUEST = ("{reference} expired: it was made more than {hours} hours ago."
                   " The visitor must send a new request.")


def handle_decide(sender, status, reference, table):
    if not access.is_approver(sender, table):
        return "Only the approver can decide a request."
    if reference is None:
        waiting = access.waiting_for(sender, table)
        if len(waiting) != 1:
            return whatsapp.waiting_body(waiting)
        reference = waiting[0]["reference"]

    visit = visits.get(reference)
    if visit is None:
        return f"No request has reference {reference}."
    if visit["status"] == db.EXPIRED:
        return EXPIRED_REQUEST.format(reference=reference, hours=config.PASS_HOURS)
    # Each reason has its own two approvers. Nobody decides another's request.
    by = access.role(sender, visit, table)
    if not by:
        return f"{reference} goes to another approver. You cannot decide it."
    main, backup = people.approvers_for(table, visit["reason"])
    phone = main if by == db.BY_MAIN else backup
    decided = visits.decide(reference, status, by, phone)
    if not decided:
        now_status = visits.get(reference)["status"]
        if now_status == db.EXPIRED:
            return EXPIRED_REQUEST.format(reference=reference, hours=config.PASS_HOURS)
        return f"{reference} was already {now_status}."
    # Before the reply to the approver, so the reply is the last message sent.
    if status == db.APPROVED:
        notify.tell_guards(decided, skip=(sender,))
    return f"{reference} is now {status}.\n\n{whatsapp.brief(visit)}"


def handle_gate(guard, sender, action, code):
    """IN takes the entry code and OUT the exit code, both from the visitor's pass.

    guard is the sender's label from guard_at(), or None.
    """
    if not guard:
        return "Only a guard can record entry and exit."
    if code is None:
        return (f"Add the {action} code from the visitor's pass."
                f" For example: {whatsapp.EXAMPLES[action]}.\n\n{whatsapp.HELP}")

    visit, kind = visits.by_code(code)
    if visit is None:
        return f"No pass has {action} code {code}. Use the code on the visitor's pass."
    if kind != action:
        return gate.WRONG_KIND[action].format(code=code)

    if visit["status"] != gate.NEEDS[action]:
        return gate.REFUSALS[action][visit["status"]]

    reference = visit["reference"]
    # Over WhatsApp the entry needs a photo of the visitor. IN only asks for
    # it. The photo itself lets them in, see handle_photo.
    if action == db.ENTRY:
        entries.wait_for_photo(whatsapp.digits(sender), reference)
        return whatsapp.photo_request(visit, code)

    done = entries.check_out(reference, guard)
    if done is None:
        return gate.REFUSALS[action][visits.get(reference)["status"]]
    return whatsapp.pass_body(done)


def handle_photo(guard, sender, media_id):
    """The guard sent a picture. It lets in the visitor named by the last IN."""
    if not guard:
        return "Only a guard can record entry and exit."

    reference, entered = entries.enter_with_photo(
        whatsapp.digits(sender), PHOTO_MINUTES, media_id, guard
    )
    if reference is None:
        return (
            "No entry is waiting for a photo.\n"
            f"Send IN <entry code>, then the photo within {PHOTO_MINUTES} minutes."
        )

    visit = visits.get(reference)
    if visit is None:
        return f"No pass has code {reference}."
    if not entered:
        return gate.REFUSALS["entry"][visit["status"]]
    return whatsapp.pass_body(visit)


def handle_lookup(guard, sender, key, table):
    """A reference or a pass code. The reply repeats only the code that was sent."""
    if not guard and not access.is_approver(sender, table):
        return None
    visit, kind = visits.by_code(key)
    if visit is not None:
        return whatsapp.pass_body(visit, key, kind)
    visit = visits.get(key)
    if visit is None:
        return f"No pass has code {key}."
    return whatsapp.pass_body(visit)


@bp.post("/webhook/whatsapp")
def whatsapp_reply():
    if not access.signature_ok():
        return "", 403

    payload = request.get_json(silent=True) or {}
    # Meta accepts every message first and reports a failed delivery only
    # here, later. Without this line a lost approval request leaves no trace.
    for recipient, code, reason in whatsapp.read_failures(payload):
        log.error("WhatsApp could not deliver to %s: error %s, %s",
                         recipient, code, reason)

    message_id, sender, text, photo = whatsapp.read_incoming(payload)
    if sender is None:
        return "", 200
    table = people.approver_table()
    guard = access.guard_at(sender)
    if not (access.is_approver(sender, table) or guard or access.is_admin_phone(sender)):
        return "", 200
    if not db.is_new_message(message_id):
        return "", 200

    # The message id is spent from here on, so Meta's retry would be ignored.
    # A failure must therefore end in a reply that asks for the message again.
    try:
        answer = answer_message(sender, text, photo, table, guard)
    except Exception as failure:
        # Unexpected, so the log keeps the traceback to find the line.
        log.exception("Could not handle a WhatsApp message: %s", failure)
        answer = "Something went wrong on the server. Send that again."

    if answer:
        notify.reply_to(sender, answer)
    return "", 200


def answer_message(sender, text, photo, table, guard):
    if photo:
        return handle_photo(guard, sender, photo)

    kind, value, key = whatsapp.read_reply(text)
    if kind == "key":
        return handle_key(sender, guard)
    if kind == "decide":
        return handle_decide(sender, value, key, table)
    if kind == "gate":
        return handle_gate(guard, sender, value, key)
    if kind == "lookup":
        return handle_lookup(guard, sender, key, table)
    if access.is_approver(sender, table):
        return whatsapp.waiting_body(access.waiting_for(sender, table))
    return whatsapp.HELP


def handle_key(sender, guard):
    """KEY from the gate desk or the admin number gets that number's key.

    A guard added on the admin page gets a new key of their own. Only its hash
    is stored, so the old one cannot be sent again.
    """
    answers = []
    for which in access.FORGOT_KEYS:
        key, phone = access.key_and_phone(which)
        if key and whatsapp.same_number(sender, phone):
            answers.append(whatsapp.key_body(which, key))
    if guard and not whatsapp.same_number(sender, config.GUARD):
        own = people.renew_guard_key("+" + whatsapp.digits(sender))
        if own:
            answers.append(whatsapp.own_key_body(own))
    return "\n\n".join(answers) or whatsapp.HELP

"""The WhatsApp webhook: approvers decide, guards record entry and exit."""


import logging

from flask import Blueprint, request

from core import config, db, limits
from models import audit, blacklist, entries, people, staff, visits
from routes import access, gate
from services import notify, whatsapp

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


def handle_decide(sender, status, reference, table, help_lines=whatsapp.HELP):
    if not access.is_approver(sender):
        return "Only an approver can decide a request."
    if reference is None:
        waiting = access.waiting_for(sender, table)
        if len(waiting) != 1:
            return whatsapp.waiting_body(waiting, help_lines)
        reference = waiting[0]["reference"]

    visit = visits.get(reference)
    by, refused = decider(sender, reference, visit, table)
    if refused:
        return refused
    main, backup = people.approvers_for(table, visit)
    phone = main if by == db.BY_MAIN else backup
    decided = visits.decide(reference, status, by, phone)
    if not decided:
        return not_decided(reference)
    # Before the reply to the approver, so the reply is the last message sent.
    if status == db.APPROVED:
        notify.tell_guards(decided, skip=(sender,))
    return f"{reference} is now {status}.\n\n{whatsapp.brief(visit)}"


def decider(sender, reference, visit, table):
    """(main or backup, None) when this approver may decide the visit, else (None, why not)."""
    if visit is None:
        return None, (f"No request has reference {reference}."
                      " Check the reference in the request message.")
    if visit["status"] == db.EXPIRED:
        return None, EXPIRED_REQUEST.format(reference=reference, hours=config.PASS_HOURS)
    # Each reason has its own two approvers. Nobody decides another's request.
    by = access.role(sender, visit, table)
    if not by:
        return None, f"{reference} goes to another approver. You cannot decide it."
    return by, None


def not_decided(reference):
    """The reply when the decision found the request no longer open."""
    now_status = visits.get(reference)["status"]
    if now_status == db.EXPIRED:
        return EXPIRED_REQUEST.format(reference=reference, hours=config.PASS_HOURS)
    if now_status in db.OPEN_STATUSES:
        return f"{reference} cannot be approved: the number is on the blacklist."
    return f"{reference} was already {now_status}."


def handle_gate(guard, sender, action, code, help_lines=whatsapp.HELP):
    """IN with the entry code, OUT with the exit code. guard is the sender's label, or None."""
    if not guard:
        return "Only a guard can record entry and exit."
    if code is None:
        return (f"Add the {action} code from the visitor's pass."
                f" For example: {whatsapp.EXAMPLES[action]}.\n\n{help_lines}")

    visit, kind = visits.by_code(code)
    if visit is None:
        return f"No pass has {action} code {code}. Use the code on the visitor's pass."
    why = gate.refusal(visit, action, kind, code, guard)
    if why:
        return why

    # IN only asks for the photo. The photo lets the visitor in, see handle_photo.
    if action == db.ENTRY:
        return ask_for_photo(sender, visit, code)
    done = entries.check_out(visit["reference"], guard)
    if done is None:
        return gate.REFUSALS[action][visits.get(visit["reference"])["status"]]
    return whatsapp.pass_body(done)


def ask_for_photo(sender, visit, code):
    """The reply to IN: send the photo, or the photo this guard still owes."""
    pending = entries.wait_for_photo(whatsapp.digits(sender), visit["reference"], PHOTO_MINUTES)
    if pending:
        return whatsapp.photo_owed(visits.get(pending))
    return whatsapp.photo_request(visit, code)


def handle_cancel(guard, sender):
    """CANCEL drops the photo this guard owes, so the next IN can start."""
    if not guard:
        return "Only a guard can record entry and exit."
    dropped = entries.cancel_photo(whatsapp.digits(sender))
    if dropped is None:
        return "No photo is waiting. Send IN and the entry code to start."
    return whatsapp.photo_cancelled(visits.get(dropped))


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
        # Still approved means the number joined the blacklist after the IN.
        if visit["status"] == db.APPROVED:
            gate.stopped_at_gate(visit, guard)
        return gate.REFUSALS["entry"].get(visit["status"], gate.BLACKLISTED)
    return whatsapp.pass_body(visit)


def handle_staff(guard, kind, code):
    """A guard sent an allow list code: alone it toggles, IN or OUT says which. The move is
    recorded at once. The reply names them. A blacklisted number cannot enter, but can leave."""
    if not guard:
        return "Only a guard can record entry and exit."
    if limits.too_many("allow-code", gate.CODES_PER_MINUTE, 60, who=guard):
        return gate.TOO_MANY_CODES
    person = staff.by_code(code)
    if person is None:
        return f"No one on the allow list has the code {code}. Check the code, or ask the admin."
    kind, stamp, new, told = notify.staff_moved(person, guard, kind,
                                                may_enter=not blacklist.has(person["phone"]))
    if stamp is None:
        gate.stopped_code(person, guard)
        return f"{person['name']}: {gate.BLACKLISTED}"
    if kind == db.EXIT:
        return whatsapp.staff_exit_reply(person, stamp, new)
    return whatsapp.staff_entry_reply(person, stamp, new, told)


def handle_lookup(guard, sender, key, table):
    """A reference or a pass code. The reply repeats only the code that was sent."""
    if not guard and not access.is_approver(sender):
        return None
    if limits.too_many("lookup", gate.LOOKUPS_PER_MINUTE, 60, who=whatsapp.digits(sender)):
        return "Too many lookups. Wait a minute."
    visit, kind = visits.by_code(key)
    code = key if visit is not None else None
    if visit is None:
        visit = visits.get(key)
    # A pass code opens its pass. By reference, a guard sees only a visit on the gate board,
    # and an approver only the requests they approve. Anything else reads as no pass at all.
    approves = visit is not None and any(
        whatsapp.same_number(sender, phone) for phone in people.approvers_for(table, visit))
    if visit is None or not (code or approves or (guard and gate.on_board(visit))):
        return f"No pass has code {key}."
    body = whatsapp.pass_body(visit, code, kind, phone=not guard)
    if visit["status"] in db.EXPIRING and blacklist.has(visit["phone"]):
        # A guard with the entry code has the person at the gate.
        if guard and kind == db.ENTRY:
            gate.stopped_at_gate(visit, guard)
        return f"{gate.BLACKLISTED}\n\n{body}"
    return body


@bp.post("/webhook/whatsapp")
def whatsapp_reply():
    if not access.signature_ok():
        return "", 403

    payload = request.get_json(silent=True) or {}
    # Meta reports failed deliveries only here, so log them.
    for recipient, code, reason in whatsapp.read_failures(payload):
        log.error("WhatsApp could not deliver to %s: error %s, %s",
                         recipient, code, reason)

    for message_id, sender, text, photo in whatsapp.read_messages(payload):
        handle_message(message_id, sender, text, photo)
    return "", 200


def handle_message(message_id, sender, text, photo):
    """One message: only a known number gets an answer, and each message id acts once."""
    table = people.approver_table()
    guard = access.guard_at(sender)
    if not (access.is_approver(sender) or guard or access.is_admin_phone(sender)):
        return
    if not db.is_new_message(message_id):
        return

    # The message id is spent now, so a failure must ask for the message again.
    try:
        answer = answer_message(sender, text, photo, table, guard)
    except Exception as failure:
        # Unexpected, so the log keeps the traceback to find the line.
        log.exception("Could not handle a WhatsApp message: %s", failure)
        answer = "Something went wrong on the server. Send that again."

    if answer:
        notify.reply_to(sender, answer)


def answer_message(sender, text, photo, table, guard):
    if photo:
        return handle_photo(guard, sender, photo)

    # The help names only this sender's jobs: approver, guard, admin, or any mix.
    roles = {role for role, has in (("approver", access.is_approver(sender)),
                                    ("guard", bool(guard)),
                                    ("admin", access.is_admin_phone(sender))) if has}
    help_lines = whatsapp.help_text(roles)
    kind, value, key = whatsapp.read_reply(text)
    handlers = {
        "key": lambda: handle_key(sender, guard, help_lines),
        "cancel": lambda: handle_cancel(guard, sender),
        "decide": lambda: handle_decide(sender, value, key, table, help_lines),
        "gate": lambda: handle_gate(guard, sender, value, key, help_lines),
        "staff": lambda: handle_staff(guard, value, key),
        "lookup": lambda: handle_lookup(guard, sender, key, table),
    }
    if kind in handlers:
        return handlers[kind]()
    if "approver" in roles:
        return whatsapp.waiting_body(access.waiting_for(sender, table), help_lines)
    return help_lines


def handle_key(sender, guard, help_lines=whatsapp.HELP):
    """KEY sends the gate desk or admin its key. An added guard or admin gets a new key."""
    answers = []
    by = f"KEY on WhatsApp from +{whatsapp.digits(sender)}"
    for which in access.FORGOT_KEYS:
        key, phone = access.key_and_phone(which)
        if key and whatsapp.same_number(sender, phone):
            answers.append(whatsapp.key_body(which, key))
            audit.record(by, f"Sent the shared {which} key")
    if guard and not whatsapp.same_number(sender, config.GUARD):
        own = people.renew_key(people.GUARDS, "+" + whatsapp.digits(sender))
        if own:
            answers.append(whatsapp.own_key_body(own))
            audit.record(by, "Made a new gate key", guard)
    admin = access.added_admin_at(sender)
    if admin:
        own = people.renew_key(people.ADMINS, admin["phone"])
        if own:
            answers.append(whatsapp.own_key_body(own, "admin"))
            audit.record(by, "Made a new admin key", access.guard_label(admin))
    return "\n\n".join(answers) or help_lines

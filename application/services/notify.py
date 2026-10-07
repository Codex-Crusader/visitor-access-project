"""WhatsApp messages the app sends by itself, and their failures in the log."""

import logging
from concurrent.futures import ThreadPoolExecutor

from core import config, db
from models import people, staff, visits
from services import whatsapp

# The same logger as app.logger, so every message reaches one place.
log = logging.getLogger("app")


# How many approval messages to guards go to Meta at the same time.
GUARD_SENDS_AT_ONCE = 8


def resend_after_change(before, after):
    """Send each open request whose approver changed to the new one. Returns how many went.

    Waiting: the new approver. Asked again: the new backup, or a reminder to an approver who is
    their own backup."""
    to_send = []
    for visit in visits.open_requests():
        old, new = people.approvers_for(before, visit), people.approvers_for(after, visit)
        waiting = visit["status"] == db.PENDING
        if not whatsapp.same_number(old[0 if waiting else 1], new[0 if waiting else 1]):
            how = whatsapp.notify_approver if waiting else whatsapp.notify_backup
            to_send.append((visit, new, how))

    def send(job):
        request, pair, ask = job
        try:
            log_template_problem(ask(request, pair))
            return True
        except Exception as failure:
            log.error("Could not send %s to its new approver: %s", request["reference"], failure)
            return False

    # Together, as the guard messages go: one slow answer from Meta does not add up per request.
    with ThreadPoolExecutor(max_workers=GUARD_SENDS_AT_ONCE) as pool:
        return sum(pool.map(send, to_send))


def tell_guards(visit, skip=()):
    """Tell every guard, except skip, that a visitor is approved. Plain text: a best effort."""
    _send_to_guards([whatsapp.guard_update_body(visit)], skip, visit["reference"])


def tell_guards_many(approved):
    """Tell every guard about many approvals at once: one list, not one message per visitor."""
    if approved:
        _send_to_guards(whatsapp.guard_list_bodies(approved), (), f"{len(approved)} approvals")


def _send_to_guards(bodies, skip, about):
    try:
        phones = [config.GUARD] + [guard["phone"] for guard in people.holders(people.GUARDS)]
    except Exception as failure:
        log.error("Could not read the guards to tell them about %s: %s", about, failure)
        return
    skipped = {whatsapp.digits(phone) for phone in skip}
    to_tell = {whatsapp.digits(p): p for p in phones if whatsapp.digits(p) not in skipped}
    # Sent together, so the approver waits for one call to Meta, not one per guard.
    with ThreadPoolExecutor(max_workers=GUARD_SENDS_AT_ONCE) as pool:
        for phone in to_tell.values():
            for body in bodies:
                pool.submit(reply_to, phone, body)


def log_template_problem(problem):
    """Log a refused template: its plain text misses an approver quiet for 24 hours."""
    if problem:
        log.error("Approval template refused, sent plain text instead: %s", problem)


def reply_to(phone, text):
    try:
        whatsapp.send(phone, text)
    except Exception as failure:
        log.error("Could not reply: %s", failure)


def staff_entered(person, by):
    """Record an allow list entry, then tell the person. Returns (time, new, told).

    A repeat within a few minutes records and sends nothing. A failed message keeps the entry."""
    stamp, new = staff.record_entry(person, by)
    if not new:
        return stamp, False, False
    try:
        whatsapp.notify_staff_entry(person, stamp, by)
    except Exception as failure:
        log.error("Could not tell code %s about their entry: %s", person["code"], failure)
        return stamp, True, False
    return stamp, True, True

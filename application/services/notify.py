"""WhatsApp messages the app sends by itself, and their failures in the log."""

import logging
from concurrent.futures import ThreadPoolExecutor

from core import config, db
from models import people, staff, visits
from services import whatsapp

# The same logger as app.logger, so every message reaches one place.
log = logging.getLogger("app")


# How many resent requests go to Meta at the same time.
SENDS_AT_ONCE = 8


# What became of each resent request: sent, refused by Meta, or no answer in time.
SENT, FAILED, UNSURE = "sent", "failed", "unsure"


def resend_after_change(before, after):
    """Send each open request whose approver changed to the new one. Returns how many of them
    were sent, failed, and may have arrived, as {"sent": n, "failed": n, "unsure": n}.

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
            return SENT
        except whatsapp.Uncertain as unsure:
            log.warning("Sending %s to its new approver is uncertain: %s",
                        request["reference"], unsure)
            return UNSURE
        except Exception as failure:
            log.error("Could not send %s to its new approver: %s", request["reference"], failure)
            return FAILED

    # Together: one slow answer from Meta does not add up per request.
    with ThreadPoolExecutor(max_workers=SENDS_AT_ONCE) as pool:
        outcomes = list(pool.map(send, to_send))
    return {outcome: outcomes.count(outcome) for outcome in (SENT, FAILED, UNSURE)}


def resent_words(counts):
    """The change log's note on the open requests sent to a new approver. Empty when none."""
    if not any(counts.values()):
        return ""
    words = f". Open requests sent to them: {counts[SENT]}"
    if counts[FAILED]:
        words += f", not sent: {counts[FAILED]}"
    if counts[UNSURE]:
        words += f", may not have arrived: {counts[UNSURE]}"
    return words


def tell_guards(visit, skip=()):
    """Tell the gate desk, unless it is in skip, that a visitor is approved. Plain text."""
    _send_to_desk([whatsapp.guard_update_body(visit)], skip)


def tell_guards_many(approved):
    """Tell the gate desk about many approvals at once: one list, not one message per visitor."""
    if approved:
        _send_to_desk(whatsapp.guard_list_bodies(approved), ())


def _send_to_desk(bodies, skip):
    """The gate desk number only: it is the phone at the gate, whoever is on duty. One message
    costs less than one per guard, and the gate board lists every approved visitor anyway."""
    if any(whatsapp.same_number(config.GUARD, phone) for phone in skip):
        return
    for body in bodies:
        reply_to(config.GUARD, body)


def log_template_problem(problem):
    """Log a refused template: its plain text misses an approver quiet for 24 hours."""
    if problem:
        log.error("Approval template refused, sent plain text instead: %s", problem)


def reply_to(phone, text):
    try:
        whatsapp.send(phone, text)
    except Exception as failure:
        log.error("Could not reply: %s", failure)


def staff_moved(person, by, kind=None, may_enter=True):
    """Record an allow list entry or exit, see staff.record_move(). A new entry tells the person.
    Returns (kind, time, new, told). The time is None for an entry may_enter refused.

    A repeat within a few minutes records and sends nothing. A failed message keeps the entry."""
    kind, stamp, new = staff.record_move(person, by, kind, may_enter)
    if not new or kind != db.ENTRY:
        return kind, stamp, new, False
    try:
        whatsapp.notify_staff_entry(person, stamp, by)
    except Exception as failure:
        log.error("Could not tell code %s about their entry: %s", person["code"], failure)
        return kind, stamp, True, False
    return kind, stamp, True, True

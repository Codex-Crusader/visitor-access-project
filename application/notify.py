"""WhatsApp messages the app sends by itself, and their failures in the log."""

import logging
from concurrent.futures import ThreadPoolExecutor

import config
import people
import whatsapp

# The same logger as app.logger, so every message reaches one place.
log = logging.getLogger("app")


# How many approval messages to guards go to Meta at the same time.
GUARD_SENDS_AT_ONCE = 8


def tell_guards(visit, skip=()):
    """Tell every guard that a visitor is approved, except the numbers in skip.

    Plain text, so a guard who has not written to the app for 24 hours does
    not get it. The approval stands either way.
    """
    try:
        phones = [config.GUARD] + [guard["phone"] for guard in people.guards()]
    except Exception as failure:
        log.error("Could not read the guards to tell them about %s: %s",
                         visit["reference"], failure)
        return
    skipped = {whatsapp.digits(phone) for phone in skip}
    to_tell = {whatsapp.digits(p): p for p in phones if whatsapp.digits(p) not in skipped}
    body = whatsapp.guard_update_body(visit)
    # Sent together, so the approver waits for one call to Meta, not one per guard.
    with ThreadPoolExecutor(max_workers=GUARD_SENDS_AT_ONCE) as pool:
        for phone in to_tell.values():
            pool.submit(reply_to, phone, body)


def log_template_problem(problem):
    """The template was refused and plain text went instead. Say so, because
    plain text does not reach an approver who has been quiet for 24 hours."""
    if problem:
        log.error("Approval template refused, sent plain text instead: %s", problem)


def reply_to(phone, text):
    try:
        whatsapp.send(phone, text)
    except Exception as failure:
        log.error("Could not reply: %s", failure)

"""The background timer: escalation, automatic approval, expiry and the purge."""

import logging
import threading
from datetime import datetime, timedelta, timezone

import config
import db
import notify
import people
import visits
import whatsapp

# The same logger as app.logger, so every message reaches one place.
log = logging.getLogger("app")


# The shortest gap between background rounds, so a failed send is tried again soon.
BACKGROUND_SECONDS = 30
# The longest gap, so Neon can scale to zero. The purge runs at least this often.
IDLE_SECONDS = 3600


def auto_approve_time(moment):
    """When a request made at moment is approved by itself, as UTC, or None out of hours."""
    if not config.AUTO_APPROVE_MINUTES:
        return None
    local = moment.astimezone(config.WORK_TIMEZONE)
    if local.weekday() not in config.WORK_DAYS:
        return None
    if not config.WORK_START <= local.hour < config.WORK_END:
        return None
    due = moment + timedelta(minutes=config.AUTO_APPROVE_MINUTES)
    return due.astimezone(timezone.utc).isoformat(timespec="seconds")


def escalate_due():
    """Ask the backup approver about each unanswered request. One failure does not stop the rest."""
    table = people.approver_table()
    for visit in visits.due_for_escalation():
        if visit["status"] != db.PENDING:
            continue  # expired: nobody needs to be asked now
        try:
            approvers = people.approvers_for(table, visit["reason"])
            notify.log_template_problem(whatsapp.notify_backup(visit, approvers))
        except Exception as failure:
            log.error("Could not ask the backup approver about %s: %s",
                             visit["reference"], failure)
            continue
        visits.mark_escalated(visit["reference"])


def auto_approve_due():
    """Approve each working-hours request no one answered in time, and tell its approvers."""
    table = people.approver_table()
    for visit in visits.due_for_auto_approval():
        done = visits.decide(visit["reference"], db.APPROVED, db.BY_AUTO)
        if done is None:
            continue
        body = whatsapp.auto_approved_body(done, config.AUTO_APPROVE_MINUTES)
        # Plain text: lost to an approver quiet for 24 hours. The approval stands.
        approvers = people.approvers_for(table, done["reason"])
        for phone in dict.fromkeys(approvers):
            notify.reply_to(phone, body)
        notify.tell_guards(done, skip=approvers)


# Set when the process is about to exit. The timer stops at its next wait.
stopping = threading.Event()
# Ends the timer's wait early: set by a new request, and on exit.
wake = threading.Event()


def seconds_to_next_round():
    """How long the timer sleeps: until the next deadline, within the floor and the cap."""
    due = visits.next_due()
    if due is None:
        return IDLE_SECONDS
    # One second late, so the deadline has passed when the round reads the database.
    wait = (due - datetime.now(timezone.utc)).total_seconds() + 1
    return min(max(wait, BACKGROUND_SECONDS), IDLE_SECONDS)


def background_loop():
    """Approve, escalate, expire and purge, then sleep until the next deadline, an hour at most."""
    while True:
        wait = BACKGROUND_SECONDS
        # Also catches changes from outside this process, such as a database restore.
        db.forget_cache()
        try:
            auto_approve_due()
            escalate_due()
            expired = visits.expire_old()
            if expired:
                log.info("Marked %s passes expired", expired)
            removed = visits.purge_old()
            if removed:
                log.info("Deleted %s visit records past retention", removed)
            wait = seconds_to_next_round()
        except Exception as failure:
            # Unexpected, so the log keeps the traceback to find the line.
            log.exception("Background work failed: %s", failure)
        wake.wait(wait)
        wake.clear()
        if stopping.is_set():
            return


# Made here, started in the serving process by start_background().
background = threading.Thread(target=background_loop, daemon=True)

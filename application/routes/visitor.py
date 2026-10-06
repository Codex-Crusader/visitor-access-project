"""The visitor page's calls: the settings, a new request, and its status."""

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

import blacklist
import checks
import config
import db
import limits
import notify
import pages
import people
import timer
import visits
import whatsapp

# The same logger as app.logger, so every message reaches one place.
log = logging.getLogger("app")
bp = Blueprint("visitor", __name__)


@bp.get("/api/config")
def read_config():
    return jsonify(
        gate_desk_phone=config.GATE_DESK_PHONE,
        escalate_minutes=config.ESCALATE_MINUTES,
        retain_days=config.RETAIN_DAYS,
        pass_hours=config.PASS_HOURS,
        # Names only: the visitor never sees an approver's number. offices stays a flat list
        # of names for a phone that still runs the old script.
        **offices_or_none(),
    )


def offices_or_none():
    """The offices, flat and grouped by tag, or empty while the database cannot answer."""
    try:
        return office_lists()
    except Exception as failure:  # any failure: the visitor types the office instead
        log.error("Could not read the offices: %s", failure)
        return {"offices": [], "office_groups": []}


def office_lists():
    return {"offices": people.office_names(), "office_groups": people.office_groups()}


# The visitor does not see how or when a request is approved, or by whom.
VISITOR_PRIVATE = ("auto_approve_at", "decided_by", "decided_phone", "entered_by", "exited_by")


def visitor_view(visit):
    return {key: value for key, value in visit.items() if key not in VISITOR_PRIVATE}


@bp.post("/api/requests")
def create_request():
    # The address is public, so cap how often one caller can make the phone buzz.
    if limits.too_many("request", config.REQUESTS_PER_HOUR, 3600):
        return jsonify(error="Too many requests from here. Try again later."), 429

    payload = request.get_json(silent=True) or {}
    fields, guests, error = checks.clean_fields(payload)
    if error:
        return jsonify(error=error), 400
    if blacklist.has(fields["phone"]):
        blacklist.record_attempt(fields["phone"], fields["name"], blacklist.ASKED,
                                 fields["visiting"], blacklist.VISITOR_PAGE)
        return jsonify(error=BLOCKED), 403
    office, error = chosen_office(fields["reason"], payload.get("office"))
    if error:
        # The page's list may be old: an office was deleted, or the list did not load.
        return jsonify(error=error, **office_lists()), 400
    if office:
        fields["visiting"] = office

    auto_at = timer.auto_approve_time(datetime.now(timezone.utc))
    visit = visits.create(fields, guests, auto_at, office)
    try:
        approvers = people.approvers_for(people.approver_table(), visit)
        notify.log_template_problem(whatsapp.notify_approver(visit, approvers))
    except Exception as sending_failed:
        visits.delete(visit["reference"])
        log.error("WhatsApp send failed: %s", sending_failed)
        return jsonify(error="Could not reach the approver. Try again."), 502
    # The new request brings new deadlines, so the timer works out when to run next.
    timer.wake.set()
    return jsonify(visitor_view(visit)), 201


# Neutral on purpose: the page does not say why.
BLOCKED = "This number cannot request a visit. Call the gate desk."


def chosen_office(reason, given):
    """(office, error). The office must be on the list. With no offices, nothing changes."""
    if reason != config.OFFICE_REASON:
        return None, None
    names = people.office_names()
    if not names:
        return None, None
    wanted = str(given or "").strip().lower()
    found = [name for name in names if name.lower() == wanted]
    if not found:
        return None, "That office is not on the list now. Choose again."
    return found[0], None


@bp.get("/api/visit/<token>")
def read_visit(token):
    """The visitor's own view. The token is long, so the code stays private."""
    found = visits.visitor_pass(token)
    if found is None:
        return jsonify(error="No request with that token"), 404
    visit, codes = found
    # One code at a time: entry until the visitor is in, then exit. Neither before or after.
    visit = visitor_view(visit)
    showing = {db.APPROVED: db.ENTRY, db.INSIDE: db.EXIT}.get(visit["status"])
    if showing:
        visit[f"{showing}_code"] = codes[showing]
    # The phone asks again with this tag, and an unchanged pass costs an empty 304.
    response = jsonify(visit)
    response.headers["Cache-Control"] = "private, no-cache"
    response.set_etag(pages.short_hash(response.get_data()))
    return response.make_conditional(request)

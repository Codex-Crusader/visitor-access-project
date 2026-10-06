"""The visitor page's calls: the settings, a new request, and its status."""

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

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
    )


# The visitor does not see how or when a request is approved, or by whom.
VISITOR_PRIVATE = ("auto_approve_at", "decided_by", "decided_phone", "entered_by", "exited_by")


def visitor_view(visit):
    return {key: value for key, value in visit.items() if key not in VISITOR_PRIVATE}


@bp.post("/api/requests")
def create_request():
    # The address is public, so cap how often one caller can make the phone buzz.
    if limits.too_many("request", config.REQUESTS_PER_HOUR, 3600):
        return jsonify(error="Too many requests from here. Try again later."), 429

    fields, guests, error = checks.clean_fields(request.get_json(silent=True) or {})
    if error:
        return jsonify(error=error), 400

    visit = visits.create(fields, guests, timer.auto_approve_time(datetime.now(timezone.utc)))
    try:
        approvers = people.approvers_for(people.approver_table(), visit["reason"])
        notify.log_template_problem(whatsapp.notify_approver(visit, approvers))
    except Exception as sending_failed:
        visits.delete(visit["reference"])
        log.error("WhatsApp send failed: %s", sending_failed)
        return jsonify(error="Could not reach the approver. Try again."), 502
    # The new request brings new deadlines, so the timer works out when to run next.
    timer.wake.set()
    return jsonify(visitor_view(visit)), 201


@bp.get("/api/visit/<token>")
def read_visit(token):
    """The visitor's own view. The token is long, so the code stays private."""
    found = visits.visitor_pass(token)
    if found is None:
        return jsonify(error="No request with that token"), 404
    visit, codes = found
    # The pass shows one code at a time: the entry code until the guard lets
    # the visitor in, then the exit code. Before approval and after the exit,
    # neither.
    visit = visitor_view(visit)
    showing = {db.APPROVED: db.ENTRY, db.INSIDE: db.EXIT}.get(visit["status"])
    if showing:
        visit[f"{showing}_code"] = codes[showing]
    # The phone asks again with this tag, and an unchanged pass costs an empty 304.
    response = jsonify(visit)
    response.headers["Cache-Control"] = "private, no-cache"
    response.set_etag(pages.short_hash(response.get_data()))
    return response.make_conditional(request)

"""The visitor page's calls: the settings, a new request, and its status."""

import logging
import re
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
VISITOR_PRIVATE = ("auto_approve_at", "decided_by", "decided_phone", "entered_by", "exited_by",
                   "request_key")


def visitor_view(visit):
    return {key: value for key, value in visit.items() if key not in VISITOR_PRIVATE}


@bp.post("/api/requests")
def create_request():
    # The address is public, so cap how often one caller can make the phone buzz.
    if limits.too_many("request", config.REQUESTS_PER_HOUR, 3600):
        return jsonify(error="Too many requests from here. Try again later."), 429

    payload = request.get_json(silent=True) or {}
    form, refused = read_form(payload)
    if refused:
        return refused
    fields, guests, office = form

    # A resend of the same form, after a slow answer, gets the first request back.
    key = payload.get("request_key")
    key = key if isinstance(key, str) and REQUEST_KEY.match(key) else None
    if key:
        earlier = visits.by_request_key(key)
        if earlier:
            return jsonify(visitor_view(earlier)), 200
    # Counted only here, so a refused or repeated form never uses up the campus's hour.
    if limits.too_many("request-all", config.REQUESTS_PER_HOUR_ALL, 3600, who="campus"):
        return jsonify(error="The campus has too many requests right now. Call the gate desk."), 429
    auto_at = timer.auto_approve_time(datetime.now(timezone.utc))
    try:
        visit = visits.create(fields, guests, auto_at, office, key)
    except visits.SameRequest as same:
        return jsonify(visitor_view(same.visit)), 200
    failed = send_to_approver(visit)
    if failed:
        return failed
    # The new request brings new deadlines, so the timer works out when to run next.
    timer.wake.set()
    return jsonify(visitor_view(visit)), 201


def read_form(payload):
    """((fields, guests, office), None), or (None, the refusal to send back)."""
    fields, guests, error = checks.clean_fields(payload)
    if error:
        return None, (jsonify(error=error), 400)
    if blacklist.has(fields["phone"]):
        blacklist.record_attempt(fields["phone"], fields["name"], blacklist.ASKED,
                                 fields["visiting"], blacklist.VISITOR_PAGE)
        return None, (jsonify(error=BLOCKED), 403)
    office, error = chosen_office(fields["reason"], payload.get("office"))
    if error:
        # The page's list may be old: an office was deleted, or the list did not load.
        return None, (jsonify(error=error, **office_lists()), 400)
    if office:
        fields["visiting"] = office
    return (fields, guests, office), None


def send_to_approver(visit):
    """None when the message went, or kept on an uncertain send. Else the refusal."""
    try:
        approvers = people.approvers_for(people.approver_table(), visit)
        notify.log_template_problem(whatsapp.notify_approver(visit, approvers))
    except whatsapp.Uncertain as unsure:
        # It may have arrived, so the request stays and the reminder asks again. A person must
        # see it, so it is not approved by itself.
        visits.stop_auto_approval(visit["reference"])
        log.warning("WhatsApp send uncertain for %s, kept: %s", visit["reference"], unsure)
    except Exception as sending_failed:
        visits.delete(visit["reference"])
        log.error("WhatsApp send failed: %s", sending_failed)
        return jsonify(error="Could not reach the approver. Try again."), 502
    return None


# Made by the visitor's browser: random, so only that browser can know it.
REQUEST_KEY = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

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
    # One code at a time: entry until the visitor is in, then exit. Not before, and not after.
    visit = visitor_view(visit)
    showing = {db.APPROVED: db.ENTRY, db.INSIDE: db.EXIT}.get(visit["status"])
    if showing:
        visit[f"{showing}_code"] = codes[showing]
    # The phone asks again with this tag, and an unchanged pass costs an empty 304.
    response = jsonify(visit)
    response.headers["Cache-Control"] = "private, no-cache"
    response.set_etag(pages.short_hash(response.get_data()))
    return response.make_conditional(request)

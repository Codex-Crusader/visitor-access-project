"""The admin page's calls, and the forgotten-key messages."""

import base64
import logging

from flask import Blueprint, Response, jsonify, request, stream_with_context

from core import checks, config, db, limits
from models import audit, entries, people, staff, visits
from routes import access, pages, team
from services import export, notify, timer, whatsapp

# The same logger as app.logger, so every message reaches one place.
log = logging.getLogger("app")
bp = Blueprint("admin", __name__)


# The status filters on the admin page. "waiting" is both open statuses.
ADMIN_FILTERS = {
    "all": None,
    "waiting": db.OPEN_STATUSES,
    "approved": (db.APPROVED,),
    "inside": (db.INSIDE,),
    "closed": (db.CLOSED,),
    "declined": (db.DECLINED,),
    "expired": (db.EXPIRED,),
}
ADMIN_PAGE = 50


@bp.get("/api/admin/visits")
def admin_visits():
    """One page of requests, newest first. The next page: ?after=<created_at>|<reference>."""
    refused = access.admin_refusal()
    if refused:
        return refused
    status = request.args.get("status", "all")
    if status not in ADMIN_FILTERS:
        return jsonify(error="Unknown status filter"), 400
    search = " ".join(request.args.get("q", "").split())[:checks.MAX_LENGTH]
    after = None
    if request.args.get("after"):
        parts = request.args["after"].split("|")
        if len(parts) != 2:
            return jsonify(error="Bad page cursor"), 400
        after = tuple(parts)

    rows, cursor = visits.admin_page(ADMIN_FILTERS[status], search, after, ADMIN_PAGE)
    table = people.approver_table()
    for visit in rows:
        visit["approvers"] = list(people.approvers_for(table, visit))
    return jsonify(visits=rows, next="|".join(cursor) if cursor else None)


BULK_LIMIT = 100
DECISIONS = {"approve": db.APPROVED, "decline": db.DECLINED}


@bp.post("/api/admin/decide")
def bulk_decide():
    """A super admin approves or declines many waiting requests at once.

    Each one goes through the same statement as a YES, so a request that was decided meanwhile,
    expired, or has a blacklisted number is skipped, with the reason."""
    refused = access.admin_refusal() or access.super_refusal()
    if refused:
        return refused
    status, references, problem = read_bulk(checks.json_object(request.get_json(silent=True)))
    if problem:
        return jsonify(error=problem), 400

    me = access.admin_caller()
    done, skipped = [], []
    for reference in references:
        decided = visits.decide(reference, status, db.BY_ADMIN, me)
        if decided:
            done.append(decided)
        else:
            skipped.append({"reference": reference, "why": why_not_decided(reference, status)})
    if status == db.APPROVED:
        notify.tell_guards_many(done)
    if done:
        audit.record(me, f"{'Approved' if status == db.APPROVED else 'Declined'} {len(done)}"
                     " requests at once", ", ".join(v["reference"] for v in done))
    return jsonify(decided=[v["reference"] for v in done], skipped=skipped)


def read_bulk(payload):
    """(status, references, problem) from a bulk decision's JSON. Repeats are dropped."""
    status = DECISIONS.get(str(payload.get("decision") or ""))
    given = payload.get("references")
    if status is None or not isinstance(given, list) or not given:
        return None, None, "Choose the requests, and approve or decline."
    # Refused before the first decision, so a bad one never stops the list halfway.
    if any(checks.clean_text(str(ref)) is None for ref in given):
        return None, None, "A reference has a character that is not allowed."
    references = list(dict.fromkeys(
        whatsapp.normalize_reference(str(ref)) or str(ref).upper() for ref in given))
    if len(references) > BULK_LIMIT:
        return None, None, f"Choose {BULK_LIMIT} requests at most at once."
    return status, references, None


def why_not_decided(reference, status):
    visit = visits.get(reference)
    if visit is None:
        return "No request has this reference."
    if visit["status"] == db.EXPIRED:
        return "Expired."
    if visit["status"] in db.OPEN_STATUSES and status == db.APPROVED:
        return "The number is on the blacklist."
    return f"Already {visit['status']}."


@bp.get("/api/admin/photo/<reference>")
def admin_photo(reference):
    """The gate page's photo of a visitor, as a data URL. A WhatsApp photo is not stored.

    A face is the most private thing the app keeps, so only a super admin sees it."""
    refused = access.admin_refusal() or access.super_refusal()
    if refused:
        return refused
    photo = entries.photo_of(reference)
    if photo is None or photo["image"] is None:
        return jsonify(error="No photo is stored for this visit."), 404
    response = jsonify(photo=checks.PHOTO_PREFIX + base64.b64encode(photo["image"]).decode(),
                       taken_at=photo["taken_at"])
    # A face is personal, so no browser or proxy keeps a copy.
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/api/admin/summary")
def admin_summary():
    """Counts by status, who approves each reason, and the lists of people and offices."""
    refused = access.admin_refusal()
    if refused:
        return refused
    response = jsonify(
        counts=visits.status_counts(),
        approvers=approver_rows(people.approver_table()),
        **team.lists(),
        # Only here, not after each change: with many staff members it is the longest list.
        staff_today=staff.today(),
        escalate_minutes=config.ESCALATE_MINUTES,
        auto_approve_minutes=config.AUTO_APPROVE_MINUTES,
        work_hours=[config.WORK_START, config.WORK_END],
        work_days=[config.WEEKDAYS[day] for day in sorted(config.WORK_DAYS)],
        retain_days=config.RETAIN_DAYS,
        pass_hours=config.PASS_HOURS,
        setup_gaps=setup_gaps(),
    )
    # The page asks every minute. An unchanged summary costs an empty 304, as the gate board.
    response.headers["Cache-Control"] = "no-store"
    response.set_etag(pages.short_hash(response.get_data()))
    return response.make_conditional(request)


# A random key of 20 or more characters has many different ones.
DISTINCT_KEY_CHARACTERS = 10
# The example number in the setup guide. Nobody answers it.
EXAMPLE_DESK_PHONE = "+912200000000"


def setup_gaps():
    """Server settings still at a demo value. Warnings only: the app runs, but not as it should."""
    gaps = [*phone_gaps(), *setting_gaps(), *approver_gaps()]
    if config.TEMPLATE_FALLBACK:
        gaps.append("TEMPLATE_FALLBACK is on. It hides a template that Meta refuses."
                    " Turn it off when Meta approves the visit_request template.")
    return gaps


def phone_gaps():
    gaps = []
    if whatsapp.same_number(config.GATE_DESK_PHONE, EXAMPLE_DESK_PHONE):
        gaps.append(f"GATE_DESK_PHONE is the example number {EXAMPLE_DESK_PHONE}. Call gate desk"
                    " on the visitor page dials a number that nobody answers.")
    if access.admin_phone_is_guard():
        gaps.append("ADMIN_PHONE is a guard's number, so Forgot admin key? is off."
                    " Set it to the admin's own WhatsApp number.")
    elif not config.ADMIN_PHONE_SET:
        gaps.append("ADMIN_PHONE is not set, so Forgot admin key? sends the admin key to"
                    " MAIN_APPROVER. Set it to the admin's own WhatsApp number.")
    return gaps


def setting_gaps():
    gaps = []
    if not config.STAFF_ENTRY_TEMPLATE:
        gaps.append("STAFF_ENTRY_TEMPLATE is not set, so most staff get no WhatsApp message about"
                    " their entry. Get the staff_entry template approved, then set it.")
    for name, key in (("GATE_KEY", config.GATE_KEY), ("ADMIN_KEY", config.ADMIN_KEY)):
        if key and len(set(key)) < DISTINCT_KEY_CHARACTERS:
            gaps.append(f"{name} repeats a few characters, so it is easy to guess. Make a random"
                        f" one with: {config.MAKE_KEY}")
    return gaps


def approver_gaps():
    guards = [config.GUARD] + [guard["phone"] for guard in people.holders(people.GUARDS)]
    both = sorted({phone for phone in guards if access.is_approver(phone)})
    if not both:
        return []
    return [f"{', '.join(both)} can approve a visit and also let the visitor in. If the"
            " campus wants two people for that, give the approvals to other numbers."]


def approver_rows(table):
    """Each reason's pair, and its automatic approval time: None for the default."""
    return [{"reason": reason, "main": main, "backup": backup,
             "auto_minutes": table["auto"]["reasons"].get(reason)}
            for reason, (main, backup) in table["reasons"].items()]


@bp.post("/api/admin/approvers")
def set_approvers():
    """Change one reason's approver and backup. An empty backup means the approver is both."""
    refused = access.admin_refusal()
    if refused:
        return refused
    payload = checks.json_object(request.get_json(silent=True))
    reason = payload.get("reason")
    # Each office has its own pair, under the reasons on the Approvers tab.
    if reason not in config.REASONS or reason == config.OFFICE_REASON:
        return jsonify(error="Unknown reason"), 400
    main, backup, problems = team.read_pair(payload)
    sent, minutes, minutes_problem = team.read_minutes(payload)
    if minutes_problem:
        problems["auto_minutes"] = minutes_problem
    if problems:
        return jsonify(error="Check the numbers.", fields=problems), 400
    before = people.approver_table()
    old_main, old_backup = before["reasons"][reason]
    people.save_approvers(reason, main, backup)
    if sent:
        people.save_auto_minutes(reason, minutes)
    after = people.approver_table()
    resent = notify.resend_after_change(before, after)
    moved = timer.retime_open_requests(after) if sent else 0
    detail = (f"{reason}: from {old_main}, backup {old_backup}, to {main}, backup {backup}."
              f" Open requests sent to them: {resent}")
    if sent and minutes != before["auto"]["reasons"].get(reason):
        detail += f". Approves by itself: {team.auto_words(minutes)}" + team.moved_line(moved)
    audit.record(access.admin_caller(), "Changed the approvers", detail)
    return jsonify(approvers=approver_rows(after))


FORGOT_PER_HOUR = 3
FORGOT_ALL_PER_HOUR = 10


@bp.post("/api/forgot-key/<which>")
def forgot_key(which):
    """Send a key by WhatsApp to its own fixed number. The answer never holds the key."""
    if which not in access.FORGOT_KEYS:
        return jsonify(error="Unknown key"), 404
    if which == "admin" and config.ADMIN_LOCKED:
        return jsonify(error=config.ADMIN_LOCKED), 503
    if which == "admin" and access.admin_phone_is_guard():
        return jsonify(error=access.ADMIN_PHONE_IS_GUARD), 503
    if (limits.too_many(f"forgot-{which}", FORGOT_PER_HOUR, 3600)
            or limits.too_many(f"forgot-{which}", FORGOT_ALL_PER_HOUR, 3600, who="everyone")):
        return jsonify(error="Too many tries. Wait an hour and try again."), 429
    key, phone = access.key_and_phone(which)
    try:
        whatsapp.send(phone, whatsapp.key_body(which, key))
    except Exception as failure:
        log.error("Could not send the %s key: %s", which, failure)
        return jsonify(error="Could not send the key. Try again in a minute."), 502
    audit.record("Forgot key button", f"Sent the shared {which} key",
                 f"to the number that ends in {whatsapp.digits(phone)[-4:]}")
    return jsonify(sent_to=whatsapp.digits(phone)[-4:])


@bp.get("/api/admin/export.csv")
def admin_export_csv():
    """The whole visit log, with who decided and which guard let each visitor in and out."""
    refused = access.admin_refusal() or access.super_refusal()
    if refused:
        return refused
    return Response(
        export.csv_text(export.VISIT_COLUMNS, export.visit_rows()),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{export.file_name("visits", "csv")}"'},
    )


@bp.get("/api/admin/staff-entries.csv")
def admin_staff_entries_csv():
    """The staff entry log: each allow list entry and the guard who recorded it."""
    refused = access.admin_refusal() or access.super_refusal()
    if refused:
        return refused
    response = Response(
        export.staff_entries_csv(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{export.file_name("staff-entries", "csv")}"'},
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/api/admin/export.zip")
def admin_export_zip():
    """The visit log and every gate page photo, in one ZIP. Staff entries are a separate file.

    Super admins only: it holds every visitor's details and face."""
    refused = access.admin_refusal() or access.super_refusal()
    if refused:
        return refused
    # noinspection PyTypeChecker
    # noinspection PyTypeChecker
    response = Response(
        stream_with_context(export.zip_parts()),
        mimetype="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="{export.file_name("visit-log", "zip")}"'},
    )
    # Faces and personal details: no browser or proxy keeps a copy.
    response.headers["Cache-Control"] = "no-store"
    return response

"""The admin page's calls, and the forgotten-key messages."""

import base64
import logging

from flask import Blueprint, Response, jsonify, request, stream_with_context

import access
import audit
import checks
import config
import db
import entries
import export
import limits
import notify
import people
import visits
import whatsapp
from routes import team

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
    payload = request.get_json(silent=True) or {}
    status = DECISIONS.get(payload.get("decision"))
    given = payload.get("references")
    if status is None or not isinstance(given, list) or not given:
        return jsonify(error="Choose the requests, and approve or decline."), 400
    references = list(dict.fromkeys(
        whatsapp.normalize_reference(str(ref)) or str(ref).upper() for ref in given))
    if len(references) > BULK_LIMIT:
        return jsonify(error=f"Choose {BULK_LIMIT} requests at most at once."), 400

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
    """The gate page's photo of a visitor, as a data URL. A WhatsApp photo is not stored."""
    refused = access.admin_refusal()
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
    return jsonify(
        counts=visits.status_counts(),
        approvers=approver_rows(people.approver_table()),
        **team.lists(),
        escalate_minutes=config.ESCALATE_MINUTES,
        auto_approve_minutes=config.AUTO_APPROVE_MINUTES,
        work_hours=[config.WORK_START, config.WORK_END],
        work_days=[config.WEEKDAYS[day] for day in sorted(config.WORK_DAYS)],
        retain_days=config.RETAIN_DAYS,
        pass_hours=config.PASS_HOURS,
    )


def approver_rows(table):
    return [{"reason": reason, "main": main, "backup": backup}
            for reason, (main, backup) in table["reasons"].items()]


@bp.post("/api/admin/approvers")
def set_approvers():
    """Change one reason's approver and backup. An empty backup means the approver is both."""
    refused = access.admin_refusal()
    if refused:
        return refused
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason")
    # Each office has its own pair, under the reasons on the Approvers tab.
    if reason not in config.REASONS or reason == config.OFFICE_REASON:
        return jsonify(error="Unknown reason"), 400
    problems = {}
    main = checks.clean_phone(payload.get("main"))
    # An empty backup means the approver is also the backup: they get a reminder instead.
    backup_given = str(payload.get("backup") or "").strip()
    backup = checks.clean_phone(backup_given) if backup_given else main
    if not main:
        problems["main"] = team.PHONE_HINT.format(who="approver")
    if backup_given and not backup:
        problems["backup"] = team.PHONE_HINT.format(who="backup")
    if backup_given and main and backup and whatsapp.same_number(main, backup):
        problems["backup"] = team.SAME_BACKUP
    if problems:
        return jsonify(error="Check the numbers.", fields=problems), 400
    people.save_approvers(reason, main, backup)
    audit.record(access.admin_caller(), "Changed the approvers",
                 f"{reason}: {main}, backup {backup}")
    return jsonify(approvers=approver_rows(people.approver_table()))


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
    refused = access.admin_refusal()
    if refused:
        return refused
    return Response(
        export.csv_text(export.VISIT_COLUMNS, export.visit_rows()),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{export.file_name("visits", "csv")}"'},
    )


@bp.get("/api/admin/export.zip")
def admin_export_zip():
    """The visit log, the allow list entries and every gate page photo, in one ZIP."""
    refused = access.admin_refusal()
    if refused:
        return refused
    response = Response(
        stream_with_context(export.zip_parts()),
        mimetype="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="{export.file_name("visit-log", "zip")}"'},
    )
    # Faces and personal details: no browser or proxy keeps a copy.
    response.headers["Cache-Control"] = "no-store"
    return response

"""The admin page's calls, and the forgotten-key messages."""

import base64
import csv
import io
import logging
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request

import access
import checks
import config
import db
import entries
import limits
import people
import visits
import whatsapp

# The same logger as app.logger, so every message reaches one place.
log = logging.getLogger("app")
bp = Blueprint("admin", __name__)


# The whole history, with every personal detail. Only the admin can download it.
EXPORT_COLUMNS = (
    "reference", "name", "phone", "address", "reason", "visiting", "guests",
    "status", "created_at", "escalated_at", "decided_at", "decided_by",
    "entered_at", "exited_at", "photo_at", "entered_by", "exited_by",
)

# Spreadsheets run a cell starting with these as a formula. A leading quote stops that.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def visit_log():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for visit in visits.all_visits():
        row = dict(visit)
        row["guests"] = ", ".join(row["guests"])
        writer.writerow([safe_cell(row.get(c)) for c in EXPORT_COLUMNS])

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="visits-{stamp}.csv"'},
    )


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
        visit["approvers"] = list(people.approvers_for(table, visit["reason"]))
    return jsonify(visits=rows, next="|".join(cursor) if cursor else None)


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
    """Counts by status, and who approves each reason."""
    refused = access.admin_refusal()
    if refused:
        return refused
    return jsonify(
        counts=visits.status_counts(),
        approvers=approver_rows(people.approver_table()),
        **guard_list(),
        escalate_minutes=config.ESCALATE_MINUTES,
        auto_approve_minutes=config.AUTO_APPROVE_MINUTES,
        work_hours=[config.WORK_START, config.WORK_END],
        work_days=[config.WEEKDAYS[day] for day in sorted(config.WORK_DAYS)],
        retain_days=config.RETAIN_DAYS,
        pass_hours=config.PASS_HOURS,
    )


def approver_rows(table):
    return [{"reason": reason, "main": main, "backup": backup}
            for reason, (main, backup) in table.items()]


PHONE_HINT = "Type the {who}'s number with + and the country code, like +919876543210."


@bp.post("/api/admin/approvers")
def set_approvers():
    """Change one reason's main and backup approver. Both numbers are required."""
    refused = access.admin_refusal()
    if refused:
        return refused
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason")
    if reason not in config.REASONS:
        return jsonify(error="Unknown reason"), 400
    main = checks.clean_phone(payload.get("main"))
    backup = checks.clean_phone(payload.get("backup"))
    problems = {}
    if not main:
        problems["main"] = PHONE_HINT.format(who="approver")
    if not backup:
        problems["backup"] = PHONE_HINT.format(who="backup")
    if main and backup and whatsapp.same_number(main, backup):
        problems["backup"] = "The backup must be a different number from the approver."
    if problems:
        return jsonify(error="Check the numbers.", fields=problems), 400
    people.save_approvers(reason, main, backup)
    return jsonify(approvers=approver_rows(people.approver_table()))


GUARD_NAME_LENGTH = 60


def guard_list():
    """The gate desk number, set on the server, and the guards added here."""
    return {"gate_desk": config.GUARD, "guards": people.guards()}


@bp.post("/api/admin/guards")
def add_guard():
    """Add a guard. The answer holds their new gate key, which is shown only this once."""
    refused = access.admin_refusal()
    if refused:
        return refused
    payload = request.get_json(silent=True) or {}
    raw_name = str(payload.get("name") or "")
    name = checks.clean_text(raw_name) if len(raw_name) <= GUARD_NAME_LENGTH else None
    phone = checks.clean_phone(payload.get("phone"))
    problems = {}
    if not name:
        problems["name"] = f"Type the guard's name, {GUARD_NAME_LENGTH} letters at most."
    if not phone:
        problems["phone"] = PHONE_HINT.format(who="guard")
    elif whatsapp.same_number(phone, config.GUARD):
        problems["phone"] = "This is the gate desk number. It is a guard already."
    elif whatsapp.same_number(phone, config.ADMIN_PHONE):
        problems["phone"] = "This is the admin number. A guard must not get the admin key."
    if problems:
        return jsonify(error="Check the guard's details.", fields=problems), 400
    key = people.add_guard(name, phone)
    if key is None:
        return jsonify(error="Check the guard's details.",
                       fields={"phone": "This number is a guard already."}), 400
    return jsonify(key=key, name=name, **guard_list())


def guard_from_payload():
    """The +number of an existing guard from the call's JSON, or None."""
    phone = checks.clean_phone((request.get_json(silent=True) or {}).get("phone"))
    return phone if phone and people.guard_by_phone(phone) else None


@bp.post("/api/admin/guards/new-key")
def renew_guard_key():
    """Give a guard a new gate key. Their old key stops at once."""
    refused = access.admin_refusal()
    if refused:
        return refused
    phone = guard_from_payload()
    key = people.renew_guard_key(phone) if phone else None
    if key is None:
        return jsonify(error="No guard has that number."), 404
    return jsonify(key=key, name=people.guard_by_phone(phone)["name"], **guard_list())


@bp.post("/api/admin/guards/remove")
def remove_guard():
    """Remove a guard. Their key and their WhatsApp commands stop at once."""
    refused = access.admin_refusal()
    if refused:
        return refused
    phone = guard_from_payload()
    if phone is None:
        return jsonify(error="No guard has that number."), 404
    people.remove_guard(phone)
    return jsonify(**guard_list())


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
    return jsonify(sent_to=whatsapp.digits(phone)[-4:])


@bp.get("/api/admin/export.csv")
def admin_export_csv():
    """The whole visit log, with who decided and which guard let each visitor in and out."""
    refused = access.admin_refusal()
    if refused:
        return refused
    return visit_log()

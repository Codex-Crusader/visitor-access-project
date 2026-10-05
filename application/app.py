"""Campus visitor access: web form in, WhatsApp approval out."""

import atexit
import csv
import hashlib
import hmac
import io
import re
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request

import config
import db
import whatsapp

STATIC = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=str(STATIC), static_url_path="")
if config.ADMIN_LOCKED:
    app.logger.warning(config.ADMIN_LOCKED)

FIELDS = ("name", "phone", "address", "reason", "visiting")
# The shortest gap between background rounds, so a failed send is tried again soon.
BACKGROUND_SECONDS = 30
# The longest gap. With nothing due, the timer asks the database once an hour, so
# Neon can scale to zero in between. The purge runs at least this often.
IDLE_SECONDS = 3600
# Meta is asked whether the token works at most this often. A failure is asked again sooner.
META_CHECK_SECONDS = 3600
META_RETRY_SECONDS = 300
# After IN <code>, the guard has this long to send the visitor's photo.
PHOTO_MINUTES = 10

GATE_ACTIONS = {
    "entry": (db.check_in, db.APPROVED),
    "exit": (db.check_out, db.INSIDE),
}

REFUSALS = {
    "entry": {
        db.PENDING: "Not approved yet. Do not let them in.",
        db.ESCALATED: "Not approved yet. Do not let them in.",
        db.DECLINED: "Declined. Do not let them in.",
        db.INSIDE: "Already inside.",
        db.CLOSED: "This pass is closed. The visit is over.",
        db.EXPIRED: "This pass expired. Do not let them in. They must send a new request.",
    },
    "exit": {
        db.PENDING: "Not approved yet.",
        db.ESCALATED: "Not approved yet.",
        db.DECLINED: "Declined.",
        db.APPROVED: "Not checked in yet.",
        db.CLOSED: "This pass is closed. The visit is over.",
        db.EXPIRED: "This pass expired before anyone used it.",
    },
}
# Each code does only its own job. The refusal names the code the guard needs.
WRONG_KIND = {
    db.ENTRY: "{code} is the exit code. The entry needs the entry code on the visitor's pass.",
    db.EXIT: "{code} is the entry code. The exit needs the exit code, which the"
             " visitor's pass shows once they are inside.",
}


# Every field is one line of plain text. These characters are not text:
# line breaks, terminal control codes, invisible marks, and the overrides
# that make written text run the other way. Unicode files them under
# C (other) and Z (separator). A visitor who puts them in a name is not
# writing a name. They are trying to forge extra lines in the approval
# message the approver reads on WhatsApp.
NOT_TEXT = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")
MAX_LENGTH = 200


def clean_text(value):
    """One line of plain text, or None when the value is not plain text."""
    if any(unicodedata.category(letter) in NOT_TEXT for letter in value):
        return None
    return " ".join(value.split())


def clean_fields(payload):
    """Return (fields, guests, error)."""
    fields = {}
    for key in FIELDS:
        raw = str(payload.get(key, ""))
        if len(raw) > MAX_LENGTH:
            return None, None, f"{key} is too long"
        value = clean_text(raw)
        if value is None:
            return None, None, f"{key} has characters that are not allowed"
        if not value:
            return None, None, f"{key} is required"
        fields[key] = value

    digits = "".join(c for c in fields["phone"] if c.isdigit())
    if len(digits) != 10:
        return None, None, "phone must be 10 digits"

    raw_guests = payload.get("guests") or []
    if not isinstance(raw_guests, list):
        return None, None, "guests must be a list"
    guests = []
    for guest in raw_guests[:10]:
        name = clean_text(str(guest)[:MAX_LENGTH])
        if name is None:
            return None, None, "guests have characters that are not allowed"
        if name:
            guests.append(name)
    return fields, guests, None


# (bucket, caller) -> the times of that caller's allowed calls, oldest first.
# Times only ever arrive in order, so the old ones are always at the left end
# and fall off one at a time: a call costs O(1) on average, not O(calls kept).
_hits = {}
_hits_lock = threading.Lock()
_last_sweep = [0.0]
SWEEP_SECONDS = 60
MAX_CALLERS = 10000
KEEP_SECONDS = 3600  # the longest window any limit uses


def caller():
    """The address to count against.

    Proxies append to X-Forwarded-For, so the last entry is the one our own
    proxy saw. Reading the first entry instead would let anyone invent an
    address and get a fresh allowance on every request.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded and config.BEHIND_PROXY:
        return forwarded.split(",")[-1].strip()
    return request.remote_addr or "?"


def _sweep(moment):
    """Drop callers with no call left inside the longest window.

    This reads the whole table, so it runs at most once a minute, and only
    when the table is big. Before, a full table was read on every request.
    The newest time sits at the right end, so each caller costs O(1) to judge.
    """
    if len(_hits) <= MAX_CALLERS or moment - _last_sweep[0] < SWEEP_SECONDS:
        return
    _last_sweep[0] = moment
    old = moment - KEEP_SECONDS
    for stale in [key for key, times in _hits.items() if not times or times[-1] <= old]:
        del _hits[stale]


def forget_hits():
    """Empty the rate limit table. The tests call this between checks."""
    with _hits_lock:
        _hits.clear()
        _last_sweep[0] = 0.0


def add_silent_callers(count, seconds_ago):
    """Add callers whose only call was long ago. The tests call this."""
    moment = time.time() - seconds_ago
    with _hits_lock:
        for number in range(count):
            _hits[("silent", number)] = deque([moment])


def hit_buckets():
    """How many callers the rate limit is tracking. The tests read this."""
    with _hits_lock:
        return len(_hits)


def too_many(bucket, limit, seconds, who=None):
    """True when the caller (or who, when given) is over the limit. Counts every allowed call.

    The check and the count happen under one lock. Two threads can therefore
    never both see room for one more call and both take it.
    """
    key = (bucket, caller() if who is None else who)
    moment = time.time()
    cutoff = moment - seconds
    with _hits_lock:
        times = _hits.setdefault(key, deque())
        while times and times[0] <= cutoff:
            times.popleft()
        if len(times) >= limit:
            return True
        times.append(moment)
        _sweep(moment)
    return False


def gate_key_ok():
    """A correct key always works.

    There is deliberately no lockout. The key is long random text, so guessing
    it is not a real threat, while a lockout is: people at one gate share one
    address, so one person mistyping would shut out everybody else, and the
    guard who is holding up a queue cannot tell a refusal from a wrong key.
    """
    return hmac.compare_digest(request.headers.get("X-Gate-Key", ""), config.GATE_KEY)


def admin_refusal():
    """Why an admin call is refused, or None when the key is right.

    While ADMIN_KEY is missing, the page is locked for everyone. The lock is
    checked first, so an empty key never matches an empty ADMIN_KEY.
    """
    if config.ADMIN_LOCKED:
        return jsonify(error=config.ADMIN_LOCKED), 503
    if not hmac.compare_digest(request.headers.get("X-Admin-Key", ""), config.ADMIN_KEY):
        return jsonify(error="Wrong admin key"), 403
    return None


def signature_ok():
    if not config.META_APP_SECRET:
        return True
    header = request.headers.get("X-Hub-Signature-256", "")
    if not header.startswith("sha256="):
        return False
    expected = hmac.new(
        config.META_APP_SECRET.encode(), request.get_data(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def is_approver(phone, table):
    """True when this number approves at least one reason. table is db.approver_table()."""
    return any(whatsapp.same_number(phone, who) for pair in table.values() for who in pair)


def role(phone, visit, table):
    """BY_MAIN or BY_BACKUP for this visit's approvers, or None."""
    main, backup = db.approvers_for(table, visit["reason"])
    if whatsapp.same_number(phone, main):
        return db.BY_MAIN
    if whatsapp.same_number(phone, backup):
        return db.BY_BACKUP
    return None


def waiting_for(phone, table):
    """The open requests this approver can decide, oldest first. Expired ones are left out."""
    return [visit for visit in db.open_requests()
            if visit["status"] in db.OPEN_STATUSES and role(phone, visit, table)]


def is_guard(phone):
    return whatsapp.same_number(phone, config.GUARD)


def is_admin_phone(phone):
    return whatsapp.same_number(phone, config.ADMIN_PHONE)


PHONE = re.compile(r"^\+[1-9]\d{7,14}$")


def clean_phone(text):
    """+ and digits, as +911234567890, or None when it is not a phone number."""
    number = re.sub(r"[\s().-]", "", str(text or ""))
    return number if PHONE.match(number) else None


def auto_approve_time(moment):
    """When a request made at moment is approved by itself, as UTC text, or None.

    Only a request made in working hours, on the campus clock, gets a time.
    """
    if not config.AUTO_APPROVE_MINUTES:
        return None
    local = moment.astimezone(config.WORK_TIMEZONE)
    if local.weekday() not in config.WORK_DAYS:
        return None
    if not config.WORK_START <= local.hour < config.WORK_END:
        return None
    due = moment + timedelta(minutes=config.AUTO_APPROVE_MINUTES)
    return due.astimezone(timezone.utc).isoformat(timespec="seconds")


def log_template_problem(problem):
    """The template was refused and plain text went instead. Say so, because
    plain text does not reach an approver who has been quiet for 24 hours."""
    if problem:
        app.logger.error("Approval template refused, sent plain text instead: %s", problem)


def reply_to(phone, text):
    try:
        whatsapp.send(phone, text)
    except Exception as failure:
        app.logger.error("Could not reply: %s", failure)


def short_hash(data: bytes):
    return hashlib.sha256(data).hexdigest()[:10]


# Each page asks for its scripts with a hash of their content, such as
# app.js?v=1a2b3c4d5e. A changed script gets a new address, so the browser
# keeps each version for a year and never asks for it again. The pages are
# checked on every load, which costs one small round trip that usually
# answers "not changed".
SCRIPT_VERSIONS = {path.name: short_hash(path.read_bytes()) for path in STATIC.glob("*.js")}
SCRIPT_TAG = re.compile(r'<script src="([\w.-]+\.js)"></script>')


def with_versions(html):
    return SCRIPT_TAG.sub(
        lambda tag: f'<script src="{tag[1]}?v={SCRIPT_VERSIONS[tag[1]]}"></script>', html
    )


PAGES = {
    name: with_versions((STATIC / name).read_text(encoding="utf-8"))
    for name in ("index.html", "gate.html", "admin.html")
}
PAGE_TAGS = {name: short_hash(html.encode()) for name, html in PAGES.items()}


def page(name):
    response = Response(PAGES[name], mimetype="text/html")
    response.headers["Cache-Control"] = "no-cache"
    response.set_etag(PAGE_TAGS[name])
    return response.make_conditional(request)


# The pages run their buttons from inline onclick attributes and set a few inline
# styles, so scripts and styles need 'unsafe-inline'. The policy still allows
# nothing from another site, no plugins, and no framing by another site.
CONTENT_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
    " img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none';"
    " form-action 'self'; frame-ancestors 'self'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_POLICY,
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    # The visitor's private link is in the address, so no page passes it on.
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


@app.after_request
def add_security_headers(response):
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.after_request
def keep_versioned_scripts(response):
    """A script asked for by its current hash is kept for a year."""
    version = request.args.get("v")
    if (response.status_code == 200 and version
            and version == SCRIPT_VERSIONS.get(request.path.lstrip("/"))):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


@app.get("/")
def index():
    return page("index.html")


@app.get("/gate")
def gate():
    return page("gate.html")


@app.get("/admin")
def admin():
    return page("admin.html")


_meta_check = {"at": 0.0, "ok": False}
_meta_lock = threading.Lock()


def whatsapp_ok():
    """True when Meta accepts the token. Asked at most once an hour, because the
    health address is public and must not send a call to Meta on every hit."""
    with _meta_lock:
        age = time.time() - _meta_check["at"]
        if age < (META_CHECK_SECONDS if _meta_check["ok"] else META_RETRY_SECONDS):
            return _meta_check["ok"]
        ok = whatsapp.token_works()
        _meta_check.update(at=time.time(), ok=ok)
        return ok


@app.get("/api/health")
def health():
    """For the uptime check: 200 when the database answers and Meta accepts the
    token, else 503. It says which part failed, never why."""
    if too_many("health", 30, 60):
        return jsonify(error="Too many checks. Try again in a minute."), 429
    checks = {"database": db.ping(), "whatsapp": whatsapp_ok()}
    return jsonify(checks), 200 if all(checks.values()) else 503


@app.get("/api/config")
def read_config():
    return jsonify(
        gate_desk_phone=config.GATE_DESK_PHONE,
        escalate_minutes=config.ESCALATE_MINUTES,
        retain_days=config.RETAIN_DAYS,
        pass_hours=config.PASS_HOURS,
    )


@app.post("/api/requests")
def create_request():
    # The address is public, so cap how often one caller can make the phone buzz.
    if too_many("request", config.REQUESTS_PER_HOUR, 3600):
        return jsonify(error="Too many requests from here. Try again later."), 429

    fields, guests, error = clean_fields(request.get_json(silent=True) or {})
    if error:
        return jsonify(error=error), 400

    visit = db.create(fields, guests, auto_approve_time(datetime.now(timezone.utc)))
    try:
        approvers = db.approvers_for(db.approver_table(), visit["reason"])
        log_template_problem(whatsapp.notify_approver(visit, approvers))
    except Exception as sending_failed:
        db.delete(visit["reference"])
        app.logger.error("WhatsApp send failed: %s", sending_failed)
        return jsonify(error="Could not reach the approver. Try again."), 502
    # The new request brings new deadlines, so the timer works out its next round again.
    wake.set()
    return jsonify(visit), 201


@app.get("/api/visit/<token>")
def read_visit(token):
    """The visitor's own view. The token is long, so the code stays private."""
    visit, codes = db.visitor_pass(token)
    if visit is None:
        return jsonify(error="No request with that token"), 404
    # The pass shows one code at a time: the entry code until the guard lets
    # the visitor in, then the exit code. Before approval and after the exit,
    # neither.
    # The visitor does not see how or when a request is approved.
    for private in ("auto_approve_at", "decided_by", "decided_phone"):
        visit.pop(private, None)
    showing = {db.APPROVED: db.ENTRY, db.INSIDE: db.EXIT}.get(visit["status"])
    if showing:
        visit[f"{showing}_code"] = codes[showing]
    return jsonify(visit)


# A finished visit keeps its times and loses everything personal. The privacy
# screen promises the gate desk sees the details while the visit is open, so
# a dead code must stop answering with a name, a phone number and an address.
# The CSV export still holds the whole log for whoever runs the campus.
CLOSED_PASS = ("reference", "status", "created_at", "decided_at",
               "entered_at", "exited_at", "guests")


def gate_view(visit):
    if visit["status"] != db.CLOSED:
        # The approver's number is for the admin page only.
        return {key: value for key, value in visit.items() if key != "decided_phone"}
    # The page reads guests.length, so guests is emptied rather than dropped.
    return {key: [] if key == "guests" else visit[key] for key in CLOSED_PASS}


def typed_pass(visit, code, kind):
    """The pass as the guard's code opened it. It names only that code."""
    return {**gate_view(visit), "code": code, "code_kind": kind}


@app.get("/api/pass/<key>")
def read_pass(key):
    """A pass by the code the guard typed, or by reference for a tap on the board.

    A reference shows the visitor and records nothing, so the page offers a
    button only when the guard typed the code from the visitor's pass.
    """
    if not gate_key_ok():
        return jsonify(error="Wrong gate key"), 403
    code = whatsapp.normalize_gate_code(key)
    if code:
        visit, kind = db.by_code(code)
        if visit is None:
            return jsonify(error="No pass with that code"), 404
        return jsonify(typed_pass(visit, code, kind))
    visit = db.get(whatsapp.normalize_reference(key) or key.upper())
    if visit is None:
        return jsonify(error="No pass with that code"), 404
    return jsonify(gate_view(visit))


@app.get("/api/gate/board")
def gate_board():
    """Who the gate desk expects, and who is inside now.

    Only open visits appear, so this shows nothing the pass lookup would not.
    """
    if not gate_key_ok():
        return jsonify(error="Wrong gate key"), 403
    expected, inside = db.at_gate()
    return jsonify(expected=expected, inside=inside)


@app.post("/api/pass/<key>/<action>")
def gate_action(key, action):
    """Records an entry with the entry code, or an exit with the exit code.

    The reference never records anything. It is on the approver's messages
    and the gate board, so it proves nothing about who holds the pass.
    """
    if not gate_key_ok():
        return jsonify(error="Wrong gate key"), 403
    if action not in GATE_ACTIONS:
        return jsonify(error="Unknown action"), 404

    code = whatsapp.normalize_gate_code(key)
    visit, kind = db.by_code(code) if code else (None, None)
    if visit is None:
        return jsonify(error="No pass has that code. Type the code on the visitor's pass."), 404
    if kind != action:
        return jsonify(error=WRONG_KIND[action].format(code=code),
                       visit=typed_pass(visit, code, kind)), 409

    apply_action, required = GATE_ACTIONS[action]
    if visit["status"] != required:
        return jsonify(error=REFUSALS[action][visit["status"]],
                       visit=typed_pass(visit, code, kind)), 409

    # The update itself decides. Two guards pressing at once must not both win.
    done = apply_action(visit["reference"])
    if done is None:
        fresh = db.get(visit["reference"])
        return jsonify(error=REFUSALS[action][fresh["status"]],
                       visit=typed_pass(fresh, code, kind)), 409
    return jsonify(typed_pass(done, code, kind))


EXPORT_COLUMNS = (
    "reference", "name", "phone", "address", "reason", "visiting", "guests",
    "status", "created_at", "escalated_at", "decided_at", "decided_by",
    "entered_at", "exited_at", "photo_at",
)


# Excel and Sheets run a cell that opens with one of these as a formula, so a
# visitor who types =HYPERLINK(...) as their name gets it executed on whoever
# opens the log. A leading quote makes the cell plain text again.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value):
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


@app.get("/api/export.csv")
def export_csv():
    """The whole visit log, including every entry and exit time."""
    if not gate_key_ok():
        return jsonify(error="Wrong gate key"), 403
    return visit_log()


def visit_log():
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for visit in db.all_visits():
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


@app.get("/api/admin/visits")
def admin_visits():
    """One page of every stored request, newest first.

    The next page is asked for with the cursor this one returned, as
    ?after=<created_at>|<reference>.
    """
    refused = admin_refusal()
    if refused:
        return refused
    status = request.args.get("status", "all")
    if status not in ADMIN_FILTERS:
        return jsonify(error="Unknown status filter"), 400
    search = " ".join(request.args.get("q", "").split())[:MAX_LENGTH]
    after = None
    if request.args.get("after"):
        parts = request.args["after"].split("|")
        if len(parts) != 2:
            return jsonify(error="Bad page cursor"), 400
        after = tuple(parts)

    visits, cursor = db.admin_page(ADMIN_FILTERS[status], search, after, ADMIN_PAGE)
    table = db.approver_table()
    for visit in visits:
        visit["approvers"] = list(db.approvers_for(table, visit["reason"]))
    return jsonify(visits=visits, next="|".join(cursor) if cursor else None)


@app.get("/api/admin/summary")
def admin_summary():
    """Counts by status, and who approves each reason."""
    refused = admin_refusal()
    if refused:
        return refused
    return jsonify(
        counts=db.status_counts(),
        approvers=approver_rows(db.approver_table()),
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


@app.post("/api/admin/approvers")
def set_approvers():
    """Change one reason's main and backup approver. Both numbers are required."""
    refused = admin_refusal()
    if refused:
        return refused
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason")
    if reason not in config.REASONS:
        return jsonify(error="Unknown reason"), 400
    main, backup = clean_phone(payload.get("main")), clean_phone(payload.get("backup"))
    problems = {}
    if not main:
        problems["main"] = PHONE_HINT.format(who="approver")
    if not backup:
        problems["backup"] = PHONE_HINT.format(who="backup")
    if main and backup and whatsapp.same_number(main, backup):
        problems["backup"] = "The backup must be a different number from the approver."
    if problems:
        return jsonify(error="Check the numbers.", fields=problems), 400
    db.save_approvers(reason, main, backup)
    return jsonify(approvers=approver_rows(db.approver_table()))


FORGOT_KEYS = ("gate", "admin")
FORGOT_PER_HOUR = 3
FORGOT_ALL_PER_HOUR = 10


ADMIN_PHONE_IS_GUARD = ("Set ADMIN_PHONE on the server to a number that is not the gate desk."
                        " Guards must not get the admin key.")


def key_and_phone(which):
    """(key, phone that receives it), or ("", phone) when that phone must not get the key."""
    if which == "gate":
        return config.GATE_KEY, config.GUARD
    if whatsapp.same_number(config.ADMIN_PHONE, config.GUARD):
        return "", config.ADMIN_PHONE
    return config.ADMIN_KEY, config.ADMIN_PHONE


@app.post("/api/forgot-key/<which>")
def forgot_key(which):
    """Send a key by WhatsApp to its own fixed number. The answer never holds the key."""
    if which not in FORGOT_KEYS:
        return jsonify(error="Unknown key"), 404
    if which == "admin" and config.ADMIN_LOCKED:
        return jsonify(error=config.ADMIN_LOCKED), 503
    if which == "admin" and whatsapp.same_number(config.ADMIN_PHONE, config.GUARD):
        return jsonify(error=ADMIN_PHONE_IS_GUARD), 503
    if (too_many(f"forgot-{which}", FORGOT_PER_HOUR, 3600)
            or too_many(f"forgot-{which}", FORGOT_ALL_PER_HOUR, 3600, who="everyone")):
        return jsonify(error="Too many tries. Wait an hour and try again."), 429
    key, phone = key_and_phone(which)
    try:
        whatsapp.send(phone, whatsapp.key_body(which, key))
    except Exception as failure:
        app.logger.error("Could not send the %s key: %s", which, failure)
        return jsonify(error="Could not send the key. Try again in a minute."), 502
    return jsonify(sent_to=whatsapp.digits(phone)[-4:])


@app.get("/api/admin/export.csv")
def admin_export_csv():
    """The same log as the gate desk export, for the admin key."""
    refused = admin_refusal()
    if refused:
        return refused
    return visit_log()


@app.get("/webhook/whatsapp")
def verify_webhook():
    """Meta calls this once to confirm the address belongs to us."""
    args = request.args
    if (
        args.get("hub.mode") == "subscribe"
        and args.get("hub.verify_token") == config.META_VERIFY_TOKEN
    ):
        return args.get("hub.challenge", ""), 200
    return "", 403


EXPIRED_REQUEST = ("{reference} expired: it was made more than {hours} hours ago."
                   " The visitor must send a new request.")


def handle_decide(sender, status, reference, table):
    if not is_approver(sender, table):
        return "Only the approver can decide a request."
    if reference is None:
        waiting = waiting_for(sender, table)
        if len(waiting) != 1:
            return whatsapp.waiting_body(waiting)
        reference = waiting[0]["reference"]

    visit = db.get(reference)
    if visit is None:
        return f"No request has reference {reference}."
    if visit["status"] == db.EXPIRED:
        return EXPIRED_REQUEST.format(reference=reference, hours=config.PASS_HOURS)
    # Each reason has its own two approvers. Nobody decides another's request.
    by = role(sender, visit, table)
    if not by:
        return f"{reference} goes to another approver. You cannot decide it."
    main, backup = db.approvers_for(table, visit["reason"])
    phone = main if by == db.BY_MAIN else backup
    if not db.decide(reference, status, by, phone):
        now_status = db.get(reference)["status"]
        if now_status == db.EXPIRED:
            return EXPIRED_REQUEST.format(reference=reference, hours=config.PASS_HOURS)
        return f"{reference} was already {now_status}."
    return f"{reference} is now {status}.\n\n{whatsapp.brief(visit)}"


def handle_gate(sender, action, code):
    """IN takes the entry code and OUT the exit code, both from the visitor's pass."""
    if not is_guard(sender):
        return "Only the gate desk can record entry and exit."
    if code is None:
        return (f"Add the {action} code from the visitor's pass."
                f" For example: {whatsapp.EXAMPLES[action]}.\n\n{whatsapp.HELP}")

    visit, kind = db.by_code(code)
    if visit is None:
        return f"No pass has {action} code {code}. Use the code on the visitor's pass."
    if kind != action:
        return WRONG_KIND[action].format(code=code)

    apply_action, required = GATE_ACTIONS[action]
    if visit["status"] != required:
        return REFUSALS[action][visit["status"]]

    reference = visit["reference"]
    # Over WhatsApp the entry needs a photo of the visitor. IN only asks for
    # it. The photo itself lets them in, see handle_photo.
    if action == db.ENTRY:
        db.wait_for_photo(whatsapp.digits(sender), reference)
        return whatsapp.photo_request(visit, code)

    done = apply_action(reference)
    if done is None:
        return REFUSALS[action][db.get(reference)["status"]]
    return whatsapp.pass_body(done)


def handle_photo(sender, media_id):
    """The guard sent a picture. It lets in the visitor named by the last IN."""
    if not is_guard(sender):
        return "Only the gate desk can record entry and exit."

    reference, entered = db.enter_with_photo(
        whatsapp.digits(sender), PHOTO_MINUTES, media_id
    )
    if reference is None:
        return (
            "No entry is waiting for a photo.\n"
            f"Send IN <entry code>, then the photo within {PHOTO_MINUTES} minutes."
        )

    visit = db.get(reference)
    if visit is None:
        return f"No pass has code {reference}."
    if not entered:
        return REFUSALS["entry"][visit["status"]]
    return whatsapp.pass_body(visit)


def handle_lookup(sender, key, table):
    """A reference or a pass code. The reply repeats only the code that was sent."""
    if not is_guard(sender) and not is_approver(sender, table):
        return None
    visit, kind = db.by_code(key)
    if visit is not None:
        return whatsapp.pass_body(visit, key, kind)
    visit = db.get(key)
    if visit is None:
        return f"No pass has code {key}."
    return whatsapp.pass_body(visit)


@app.post("/webhook/whatsapp")
def whatsapp_reply():
    if not signature_ok():
        return "", 403

    payload = request.get_json(silent=True) or {}
    # Meta accepts every message first and reports a failed delivery only
    # here, later. Without this line a lost approval request leaves no trace.
    for recipient, code, reason in whatsapp.read_failures(payload):
        app.logger.error("WhatsApp could not deliver to %s: error %s, %s",
                         recipient, code, reason)

    message_id, sender, text, photo = whatsapp.read_incoming(payload)
    if sender is None:
        return "", 200
    table = db.approver_table()
    if not (is_approver(sender, table) or is_guard(sender) or is_admin_phone(sender)):
        return "", 200
    if not db.is_new_message(message_id):
        return "", 200

    # The message id is spent from here on, so Meta's retry would be ignored.
    # A failure must therefore end in a reply that asks for the message again.
    try:
        answer = answer_message(sender, text, photo, table)
    except Exception as failure:
        app.logger.error("Could not handle a WhatsApp message: %s", failure)
        answer = "Something went wrong on the server. Send that again."

    if answer:
        reply_to(sender, answer)
    return "", 200


def answer_message(sender, text, photo, table):
    if photo:
        return handle_photo(sender, photo)

    kind, value, key = whatsapp.read_reply(text)
    if kind == "key":
        return handle_key(sender)
    if kind == "decide":
        return handle_decide(sender, value, key, table)
    if kind == "gate":
        return handle_gate(sender, value, key)
    if kind == "lookup":
        return handle_lookup(sender, key, table)
    if is_approver(sender, table):
        return whatsapp.waiting_body(waiting_for(sender, table))
    return whatsapp.HELP


def handle_key(sender):
    """KEY from the gate desk or the admin number gets that number's key."""
    answers = []
    for which in FORGOT_KEYS:
        key, phone = key_and_phone(which)
        if key and whatsapp.same_number(sender, phone):
            answers.append(whatsapp.key_body(which, key))
    return "\n\n".join(answers) or whatsapp.HELP


def escalate_due():
    """Ask the backup approver about every request nobody answered.

    One failed send must not stop the others, or the purge after them. The
    failed request stays pending, so the next round tries it again.
    """
    table = db.approver_table()
    for visit in db.due_for_escalation():
        if visit["status"] != db.PENDING:
            continue  # expired: nobody needs to be asked any more
        try:
            approvers = db.approvers_for(table, visit["reason"])
            log_template_problem(whatsapp.notify_backup(visit, approvers))
        except Exception as failure:
            app.logger.error("Could not ask the backup approver about %s: %s",
                             visit["reference"], failure)
            continue
        db.mark_escalated(visit["reference"])


def auto_approve_due():
    """Approve each working-hours request no one answered in time, and tell its approvers."""
    table = db.approver_table()
    for visit in db.due_for_auto_approval():
        done = db.decide(visit["reference"], db.APPROVED, db.BY_AUTO)
        if done is None:
            continue
        body = whatsapp.auto_approved_body(done, config.AUTO_APPROVE_MINUTES)
        # Plain text: lost to an approver quiet for 24 hours. The approval stands.
        for phone in dict.fromkeys(db.approvers_for(table, done["reason"])):
            reply_to(phone, body)


# Set when the process is about to exit. The timer stops at its next wait.
stopping = threading.Event()
# Ends the timer's wait early: set by a new request, and on exit.
wake = threading.Event()


def seconds_to_next_round():
    """How long the timer sleeps: until the next deadline, within the floor and the cap."""
    due = db.next_due()
    if due is None:
        return IDLE_SECONDS
    # One second late, so the deadline has passed when the round reads the database.
    wait = (due - datetime.now(timezone.utc)).total_seconds() + 1
    return min(max(wait, BACKGROUND_SECONDS), IDLE_SECONDS)


def background_loop():
    """Auto-approve and escalate requests nobody answered, expire old passes,
    then delete old records.

    The first round runs at once, so requests due while the server slept are
    handled on wake. After that it sleeps until the next deadline, an hour at
    most, instead of asking the database every 30 seconds.
    """
    while True:
        wait = BACKGROUND_SECONDS
        try:
            auto_approve_due()
            escalate_due()
            expired = db.expire_old()
            if expired:
                app.logger.info("Marked %s passes expired", expired)
            removed = db.purge_old()
            if removed:
                app.logger.info("Deleted %s visit records past retention", removed)
            wait = seconds_to_next_round()
        except Exception as failure:
            app.logger.error("Background work failed: %s", failure)
        wake.wait(wait)
        wake.clear()
        if stopping.is_set():
            return


# Made here, started in the serving process by start_background().
background = threading.Thread(target=background_loop, daemon=True)


def start_background():
    """Build the tables, then start the timer. Call it once, in the serving process.

    Importing this module starts nothing. Under gunicorn, gunicorn.conf.py
    calls this in the worker. A connection opened or a thread started at
    import would live in the master process instead, see gunicorn.conf.py.
    """
    db.init()
    background.start()
    atexit.register(stop_background)


def stop_background():
    """Stop the timer, let its current round finish, then close the database.

    gunicorn.conf.py calls this as the worker exits, and atexit does for
    python app.py. The timer is stopped first, so it never reaches a closed
    database halfway through a round. Safe to call more than once.
    """
    stopping.set()
    wake.set()
    if background.is_alive():
        background.join(timeout=10)
    db.close()


if __name__ == "__main__":
    start_background()
    app.run(host="0.0.0.0", port=5000)

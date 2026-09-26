"""Campus visitor access: web form in, WhatsApp approval out."""

import csv
import hashlib
import hmac
import io
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

import config
import db
import whatsapp

STATIC = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=str(STATIC), static_url_path="")

FIELDS = ("name", "phone", "address", "reason", "visiting")
BACKGROUND_SECONDS = 30
# After IN <code>, the guard has this long to send the visitor's photo.
PHOTO_MINUTES = 10
# The gate board lists passes approved within this many hours as expected.
# An older pass still works. It only leaves the list.
BOARD_HOURS = 24

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
    },
    "exit": {
        db.PENDING: "Not approved yet.",
        db.ESCALATED: "Not approved yet.",
        db.DECLINED: "Declined.",
        db.APPROVED: "Not checked in yet.",
        db.CLOSED: "This pass is closed. The visit is over.",
    },
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


def too_many(bucket, limit, seconds):
    """True when this caller is over the limit. Counts every allowed call.

    The check and the count happen under one lock. Two threads can therefore
    never both see room for one more call and both take it.
    """
    key = (bucket, caller())
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


def is_approver(phone):
    return any(
        whatsapp.same_number(phone, who)
        for who in (config.MAIN_APPROVER, config.BACKUP_APPROVER)
    )


def is_guard(phone):
    return whatsapp.same_number(phone, config.GUARD)


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


@app.get("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.get("/gate")
def gate():
    return send_from_directory(STATIC, "gate.html")


@app.get("/api/config")
def read_config():
    return jsonify(
        gate_desk_phone=config.GATE_DESK_PHONE,
        escalate_minutes=config.ESCALATE_MINUTES,
        retain_days=config.RETAIN_DAYS,
    )


@app.post("/api/requests")
def create_request():
    # The address is public, so cap how often one caller can make the phone buzz.
    if too_many("request", config.REQUESTS_PER_HOUR, 3600):
        return jsonify(error="Too many requests from here. Try again later."), 429

    fields, guests, error = clean_fields(request.get_json(silent=True) or {})
    if error:
        return jsonify(error=error), 400

    visit = db.create(fields, guests)
    try:
        log_template_problem(whatsapp.notify_approver(visit))
    except Exception as sending_failed:
        db.delete(visit["reference"])
        app.logger.error("WhatsApp send failed: %s", sending_failed)
        return jsonify(error="Could not reach the approver. Try again."), 502
    return jsonify(visit), 201


@app.get("/api/visit/<token>")
def read_visit(token):
    """The visitor's own view. The token is long, so the code stays private."""
    visit = db.get_by_token(token)
    if visit is None:
        return jsonify(error="No request with that token"), 404
    return jsonify(visit)


# A finished visit keeps its times and loses everything personal. The privacy
# screen promises the gate desk sees the details while the visit is open, so
# a dead code must stop answering with a name, a phone number and an address.
# The CSV export still holds the whole log for whoever runs the campus.
CLOSED_PASS = ("reference", "status", "created_at", "decided_at",
               "entered_at", "exited_at", "guests")


def gate_view(visit):
    if visit["status"] != db.CLOSED:
        return visit
    # The page reads guests.length, so guests is emptied rather than dropped.
    return {key: [] if key == "guests" else visit[key] for key in CLOSED_PASS}


@app.get("/api/pass/<reference>")
def read_pass(reference):
    if not gate_key_ok():
        return jsonify(error="Wrong gate key"), 403
    visit = db.get(reference.upper())
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
    expected, inside = db.at_gate(BOARD_HOURS)
    return jsonify(expected=expected, inside=inside)


@app.post("/api/pass/<reference>/<action>")
def gate_action(reference, action):
    if not gate_key_ok():
        return jsonify(error="Wrong gate key"), 403
    if action not in GATE_ACTIONS:
        return jsonify(error="Unknown action"), 404

    visit = db.get(reference.upper())
    if visit is None:
        return jsonify(error="No pass with that code"), 404

    apply_action, required = GATE_ACTIONS[action]
    if visit["status"] != required:
        return jsonify(error=REFUSALS[action][visit["status"]],
                       visit=gate_view(visit)), 409

    # The update itself decides. Two guards pressing at once must not both win.
    if not apply_action(visit["reference"]):
        fresh = db.get(visit["reference"])
        return jsonify(error=REFUSALS[action][fresh["status"]],
                       visit=gate_view(fresh)), 409
    return jsonify(gate_view(db.get(visit["reference"])))


EXPORT_COLUMNS = (
    "reference", "name", "phone", "address", "reason", "visiting", "guests",
    "status", "created_at", "escalated_at", "decided_at", "entered_at", "exited_at",
    "photo_at",
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


def handle_decide(sender, status, reference):
    if not is_approver(sender):
        return "Only the approver can decide a request."
    if reference is None:
        waiting = db.open_requests()
        if len(waiting) != 1:
            return whatsapp.waiting_body(waiting)
        reference = waiting[0]["reference"]

    visit = db.get(reference)
    if visit is None:
        return f"No request has reference {reference}."
    if not db.decide(reference, status):
        return f"{reference} was already {visit['status']}."
    return f"{reference} is now {status}.\n\n{whatsapp.brief(visit)}"


def handle_gate(sender, action, reference):
    if not is_guard(sender):
        return "Only the gate desk can record entry and exit."
    if reference is None:
        return f"Add the code. For example: IN VR-4022.\n\n{whatsapp.HELP}"

    visit = db.get(reference)
    if visit is None:
        return f"No pass has code {reference}."

    apply_action, required = GATE_ACTIONS[action]
    if visit["status"] != required:
        return REFUSALS[action][visit["status"]]

    # Over WhatsApp the entry needs a photo of the visitor. IN only asks for
    # it. The photo itself lets them in, see handle_photo.
    if action == "entry":
        db.wait_for_photo(whatsapp.digits(sender), reference)
        return whatsapp.photo_request(visit)

    if not apply_action(reference):
        return REFUSALS[action][db.get(reference)["status"]]
    return whatsapp.pass_body(db.get(reference))


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
            f"Send IN <code>, then the photo within {PHOTO_MINUTES} minutes."
        )

    visit = db.get(reference)
    if visit is None:
        return f"No pass has code {reference}."
    if not entered:
        return REFUSALS["entry"][visit["status"]]
    return whatsapp.pass_body(visit)


def handle_lookup(sender, reference):
    if not is_guard(sender) and not is_approver(sender):
        return None
    visit = db.get(reference)
    if visit is None:
        return f"No pass has code {reference}."
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
    if not (is_approver(sender) or is_guard(sender)):
        return "", 200
    if not db.is_new_message(message_id):
        return "", 200

    # The message id is spent from here on, so Meta's retry would be ignored.
    # A failure must therefore end in a reply that asks for the message again.
    try:
        answer = answer_message(sender, text, photo)
    except Exception as failure:
        app.logger.error("Could not handle a WhatsApp message: %s", failure)
        answer = "Something went wrong on the server. Send that again."

    if answer:
        reply_to(sender, answer)
    return "", 200


def answer_message(sender, text, photo):
    if photo:
        return handle_photo(sender, photo)

    kind, value, reference = whatsapp.read_reply(text)
    if kind == "decide":
        return handle_decide(sender, value, reference)
    if kind == "gate":
        return handle_gate(sender, value, reference)
    if kind == "lookup":
        return handle_lookup(sender, reference)
    return whatsapp.waiting_body(db.open_requests()) if is_approver(sender) else whatsapp.HELP


def escalate_due():
    """Ask the backup approver about every request nobody answered.

    One failed send must not stop the others, or the purge after them. The
    failed request stays pending, so the next round tries it again.
    """
    for visit in db.due_for_escalation():
        try:
            log_template_problem(whatsapp.notify_backup(visit))
        except Exception as failure:
            app.logger.error("Could not ask the backup approver about %s: %s",
                             visit["reference"], failure)
            continue
        db.mark_escalated(visit["reference"])


def background_loop():
    """Escalate requests nobody answered, then delete records past retention."""
    while True:
        time.sleep(BACKGROUND_SECONDS)
        try:
            escalate_due()
            removed = db.purge_old()
            if removed:
                app.logger.info("Deleted %s visit records past retention", removed)
        except Exception as failure:
            app.logger.error("Background work failed: %s", failure)


def start_background():
    db.init()
    threading.Thread(target=background_loop, daemon=True).start()


start_background()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

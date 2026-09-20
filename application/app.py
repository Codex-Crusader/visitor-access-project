"""Campus visitor access: web form in, WhatsApp approval out."""

import csv
import hashlib
import hmac
import io
import threading
import time
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, request, send_from_directory

import config
import db
import whatsapp

app = Flask(__name__, static_folder="static", static_url_path="")

FIELDS = ("name", "phone", "address", "reason", "visiting")
BACKGROUND_SECONDS = 30

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


def clean_fields(payload):
    """Return (fields, guests, error)."""
    fields = {}
    for key in FIELDS:
        value = str(payload.get(key, "")).strip()
        if not value:
            return None, None, f"{key} is required"
        if len(value) > 200:
            return None, None, f"{key} is too long"
        fields[key] = value

    digits = "".join(c for c in fields["phone"] if c.isdigit())
    if len(digits) != 10:
        return None, None, "phone must be 10 digits"

    guests = payload.get("guests") or []
    if not isinstance(guests, list):
        return None, None, "guests must be a list"
    guests = [str(g).strip()[:200] for g in guests if str(g).strip()][:10]
    return fields, guests, None


_hits = {}
_hits_lock = threading.Lock()


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


def record_hit(bucket):
    key = (bucket, caller())
    with _hits_lock:
        _hits.setdefault(key, []).append(time.time())
        if len(_hits) > 10000:  # never let the table grow without bound
            old = time.time() - 3600
            for stale in [k for k, v in _hits.items() if not any(t > old for t in v)]:
                del _hits[stale]


def too_many(bucket, limit, seconds):
    """True when this caller is over the limit. Counts every call."""
    key = (bucket, caller())
    cutoff = time.time() - seconds
    with _hits_lock:
        hits = [t for t in _hits.get(key, []) if t > cutoff]
        _hits[key] = hits
        if len(hits) >= limit:
            return True
    record_hit(bucket)
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


def reply_to(phone, text):
    try:
        whatsapp.send(phone, text)
    except Exception as failure:
        app.logger.error("Could not reply: %s", failure)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/gate")
def gate():
    return send_from_directory(app.static_folder, "gate.html")


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
        whatsapp.notify_approver(visit)
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


@app.get("/api/pass/<reference>")
def read_pass(reference):
    if not gate_key_ok():
        return jsonify(error="Wrong gate key"), 403
    visit = db.get(reference.upper())
    if visit is None:
        return jsonify(error="No pass with that code"), 404
    return jsonify(visit)


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
        return jsonify(error=REFUSALS[action][visit["status"]], visit=visit), 409

    # The update itself decides. Two guards pressing at once must not both win.
    if not apply_action(visit["reference"]):
        fresh = db.get(visit["reference"])
        return jsonify(error=REFUSALS[action][fresh["status"]], visit=fresh), 409
    return jsonify(db.get(visit["reference"]))


EXPORT_COLUMNS = (
    "reference", "name", "phone", "address", "reason", "visiting", "guests",
    "status", "created_at", "escalated_at", "decided_at", "entered_at", "exited_at",
)


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
        writer.writerow([row.get(c) or "" for c in EXPORT_COLUMNS])

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

    if not apply_action(reference):
        return REFUSALS[action][db.get(reference)["status"]]
    return whatsapp.pass_body(db.get(reference))


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

    message_id, sender, text = whatsapp.read_incoming(request.get_json(silent=True) or {})
    if sender is None:
        return "", 200
    if not (is_approver(sender) or is_guard(sender)):
        return "", 200
    if not db.is_new_message(message_id):
        return "", 200

    kind, value, reference = whatsapp.read_reply(text)
    if kind == "decide":
        answer = handle_decide(sender, value, reference)
    elif kind == "gate":
        answer = handle_gate(sender, value, reference)
    elif kind == "lookup":
        answer = handle_lookup(sender, reference)
    else:
        answer = whatsapp.waiting_body(db.open_requests()) if is_approver(sender) else whatsapp.HELP

    if answer:
        reply_to(sender, answer)
    return "", 200


def background_loop():
    """Escalate requests nobody answered, then delete records past retention."""
    while True:
        time.sleep(BACKGROUND_SECONDS)
        try:
            for visit in db.due_for_escalation():
                whatsapp.notify_backup(visit)
                db.mark_escalated(visit["reference"])
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

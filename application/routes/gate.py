"""The gate page's calls: look up a pass, the board, entry and exit, and allow list entries."""


from flask import Blueprint, jsonify, request

import access
import blacklist
import checks
import db
import entries
import limits
import notify
import staff
import visits
import whatsapp

bp = Blueprint("gate", __name__)


# The status each gate action needs.
NEEDS = {db.ENTRY: db.APPROVED, db.EXIT: db.INSIDE}

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

# A closed pass shows only its times: the gate sees personal details only while it is open.
CLOSED_PASS = ("reference", "status", "created_at", "decided_at",
               "entered_at", "exited_at", "guests")

# Never sent to the gate. The token opens the visitor's page, which shows the gate code.
# The guard decides by the name, the pass and the face. The phone stays with the admin.
GATE_PRIVATE = ("token", "address", "phone", "decided_phone", "entered_by", "exited_by",
                "request_key")


# What the gate reads for a visitor on the blacklist. Leaving is always allowed.
BLACKLISTED = "On the blacklist. Do not let them in. Tell the admin."


def gate_view(visit):
    if visit["status"] != db.CLOSED:
        shown = {key: value for key, value in visit.items() if key not in GATE_PRIVATE}
        # Only a pass that can still enter needs the check. Inside, they may always leave.
        listed = visit["status"] in db.EXPIRING and blacklist.has(visit["phone"])
        return {**shown, "blacklisted": listed}
    # The page reads guests.length, so guests is emptied rather than dropped.
    return {key: [] if key == "guests" else visit[key] for key in CLOSED_PASS}


def stopped_at_gate(visit, guard):
    blacklist.record_attempt(visit["phone"], visit["name"], blacklist.AT_GATE,
                             visit["reference"], guard)


def stopped_code(person, guard):
    blacklist.record_attempt(person["phone"], person["name"], blacklist.ALLOW_CODE,
                             person["code"], guard)


def typed_pass(visit, code, kind):
    """The pass as the guard's code opened it. It names only that code."""
    return {**gate_view(visit), "code": code, "code_kind": kind}


# Pass and reference lookups one guard may make in a minute. A busy desk makes a few.
LOOKUPS_PER_MINUTE = 60


def on_board(visit):
    """True for a visit the gate board shows: approved and still valid, or inside now."""
    return visit is not None and visit["status"] in (db.APPROVED, db.INSIDE)


@bp.get("/api/pass/<key>")
def read_pass(key):
    """A pass by its typed code, or by reference from the board. A reference records nothing.

    A reference opens only a visit on the board, so a gate key cannot read the history by
    trying references one by one. Any other reference reads as no pass at all."""
    guard = access.gate_guard()
    if not guard:
        return jsonify(error="Wrong gate key"), 403
    if limits.too_many("pass-lookup", LOOKUPS_PER_MINUTE, 60, who=guard):
        return jsonify(error="Too many lookups. Wait a minute."), 429
    code = whatsapp.normalize_gate_code(key)
    if code:
        visit, kind = visits.by_code(code)
        if visit is None:
            return jsonify(error="No pass with that code"), 404
        shown = typed_pass(visit, code, kind)
        # The entry code means the person is at the gate. A board tap is not an attempt.
        # A closed pass shows times only, with no blacklist mark.
        if shown.get("blacklisted") and kind == db.ENTRY:
            stopped_at_gate(visit, guard)
        return jsonify(shown)
    visit = visits.get(whatsapp.normalize_reference(key) or key.upper())
    if not on_board(visit):
        return jsonify(error="No pass with that code"), 404
    return jsonify(gate_view(visit))


@bp.get("/api/gate/board")
def gate_board():
    """(expected, inside) for the gate board. Only open visits."""
    guard = access.gate_guard()
    if not guard:
        return jsonify(error="Wrong gate key"), 403
    expected, inside = visits.at_gate()
    return jsonify(expected=[board_row(v) for v in expected],
                   inside=[board_row(v) for v in inside], you=guard)


def board_row(visit):
    """A board row without the phone, marked when the number is on the blacklist."""
    row = {key: value for key, value in visit.items() if key != "phone"}
    return {**row, "blacklisted": blacklist.has(visit["phone"])}


@bp.post("/api/pass/<key>/<action>")
def gate_action(key, action):
    """Record an entry or exit with its own code. The reference is public, so it records nothing."""
    guard = access.gate_guard()
    if not guard:
        return jsonify(error="Wrong gate key"), 403
    if action not in NEEDS:
        return jsonify(error="Unknown action"), 404

    code = whatsapp.normalize_gate_code(key)
    visit, kind = visits.by_code(code) if code else (None, None)
    if visit is None:
        return jsonify(error="No pass has that code. Type the code on the visitor's pass."), 404
    why = refusal(visit, action, kind, code, guard)
    if why:
        return jsonify(error=why, visit=typed_pass(visit, code, kind)), 409

    # The update itself decides. Two guards pressing at once must not both win.
    if action == db.ENTRY:
        # Checked last, so a pass that cannot enter never asks for a photo.
        photo = checks.read_photo(request.get_json(silent=True))
        if photo is None:
            return jsonify(error=checks.NO_PHOTO, visit=typed_pass(visit, code, kind)), 400
        done = entries.check_in(visit["reference"], guard, photo)
    else:
        done = entries.check_out(visit["reference"], guard)
    if done is None:
        fresh = visits.get(visit["reference"])
        # Still approved means the number joined the blacklist a moment ago.
        why = REFUSALS[action].get(fresh["status"], BLACKLISTED)
        return jsonify(error=why, visit=typed_pass(fresh, code, kind)), 409
    return jsonify(typed_pass(done, code, kind))


def refusal(visit, action, kind, code, guard):
    """Why this code cannot do this action now, or None. The page and WhatsApp share it."""
    if kind != action:
        return WRONG_KIND[action].format(code=code)
    if visit["status"] != NEEDS[action]:
        return REFUSALS[action][visit["status"]]
    if action == db.ENTRY and blacklist.has(visit["phone"]):
        stopped_at_gate(visit, guard)
        return BLACKLISTED
    return None


NO_SUCH_CODE = "No one on the allow list has that code."
# Allow list calls one guard may make in a minute, so a stolen key cannot list the names.
# The gate page makes one for each person, so one guard can take 60 people a minute.
CODES_PER_MINUTE = 60
TOO_MANY_CODES = "Too many allow list codes in a minute. Wait a minute and try again."


def staff_view(person):
    """A person on the allow list as the gate sees them: name and code, never the number."""
    return {"code": person["code"], "name": person["name"], "tag": person["tag"],
            "blacklisted": blacklist.has(person["phone"])}


@bp.get("/api/staff/<code>")
def read_staff(code):
    """A person on the allow list, by their 7-digit code. Records no entry."""
    guard = access.gate_guard()
    if not guard:
        return jsonify(error="Wrong gate key"), 403
    if limits.too_many("allow-code", CODES_PER_MINUTE, 60, who=guard):
        return jsonify(error=TOO_MANY_CODES), 429
    person = staff.by_code(staff.normalize_code(code) or "")
    if person is None:
        return jsonify(error=NO_SUCH_CODE), 404
    shown = staff_view(person)
    if shown["blacklisted"]:
        stopped_code(person, guard)
    return jsonify(shown)


@bp.post("/api/staff/<code>/entry")
def staff_entry(code):
    """Record an allow list entry at once, and send the person a WhatsApp message."""
    guard = access.gate_guard()
    if not guard:
        return jsonify(error="Wrong gate key"), 403
    person = staff.by_code(staff.normalize_code(code) or "")
    if person is None:
        return jsonify(error=NO_SUCH_CODE), 404
    if blacklist.has(person["phone"]):
        stopped_code(person, guard)
        return jsonify(error=BLACKLISTED, **staff_view(person)), 409
    stamp, new, told = notify.staff_entered(person, guard)
    return jsonify(**staff_view(person), entered_at=stamp, new=new, told=told)

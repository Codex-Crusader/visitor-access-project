"""The gate page's calls: look up a pass, the board, entry and exit."""


from flask import Blueprint, jsonify, request

import access
import checks
import db
import entries
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

# A finished visit keeps its times and loses everything personal. The privacy
# screen promises the gate desk sees the details while the visit is open, so
# a dead code must stop answering with a name, a phone number and an address.
# The CSV export still holds the whole log for whoever runs the campus.
CLOSED_PASS = ("reference", "status", "created_at", "decided_at",
               "entered_at", "exited_at", "guests")

# Never sent to the gate. The token is the visitor's private link, and it
# opens their page, which shows the gate code. The approver's number is for
# the admin page only, and so are the guards' numbers. The gate does not
# need the visitor's address.
GATE_PRIVATE = ("token", "address", "decided_phone", "entered_by", "exited_by")


def gate_view(visit):
    if visit["status"] != db.CLOSED:
        return {key: value for key, value in visit.items() if key not in GATE_PRIVATE}
    # The page reads guests.length, so guests is emptied rather than dropped.
    return {key: [] if key == "guests" else visit[key] for key in CLOSED_PASS}


def typed_pass(visit, code, kind):
    """The pass as the guard's code opened it. It names only that code."""
    return {**gate_view(visit), "code": code, "code_kind": kind}


@bp.get("/api/pass/<key>")
def read_pass(key):
    """A pass by the code the guard typed, or by reference for a tap on the board.

    A reference shows the visitor and records nothing, so the page offers a
    button only when the guard typed the code from the visitor's pass.
    """
    if not access.gate_guard():
        return jsonify(error="Wrong gate key"), 403
    code = whatsapp.normalize_gate_code(key)
    if code:
        visit, kind = visits.by_code(code)
        if visit is None:
            return jsonify(error="No pass with that code"), 404
        return jsonify(typed_pass(visit, code, kind))
    visit = visits.get(whatsapp.normalize_reference(key) or key.upper())
    if visit is None:
        return jsonify(error="No pass with that code"), 404
    return jsonify(gate_view(visit))


@bp.get("/api/gate/board")
def gate_board():
    """Who the gate desk expects, and who is inside now.

    Only open visits appear, so this shows nothing the pass lookup would not.
    """
    guard = access.gate_guard()
    if not guard:
        return jsonify(error="Wrong gate key"), 403
    expected, inside = visits.at_gate()
    return jsonify(expected=expected, inside=inside, you=guard)


@bp.post("/api/pass/<key>/<action>")
def gate_action(key, action):
    """Records an entry with the entry code, or an exit with the exit code.

    The reference never records anything. It is on the approver's messages
    and the gate board, so it proves nothing about who holds the pass.
    """
    guard = access.gate_guard()
    if not guard:
        return jsonify(error="Wrong gate key"), 403
    if action not in NEEDS:
        return jsonify(error="Unknown action"), 404

    code = whatsapp.normalize_gate_code(key)
    visit, kind = visits.by_code(code) if code else (None, None)
    if visit is None:
        return jsonify(error="No pass has that code. Type the code on the visitor's pass."), 404
    if kind != action:
        return jsonify(error=WRONG_KIND[action].format(code=code),
                       visit=typed_pass(visit, code, kind)), 409

    if visit["status"] != NEEDS[action]:
        return jsonify(error=REFUSALS[action][visit["status"]],
                       visit=typed_pass(visit, code, kind)), 409

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
        return jsonify(error=REFUSALS[action][fresh["status"]],
                       visit=typed_pass(fresh, code, kind)), 409
    return jsonify(typed_pass(done, code, kind))

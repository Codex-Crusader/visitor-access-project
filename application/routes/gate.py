"""The gate page's calls: look up a pass, the board, entry and exit, and allow list entries."""


from flask import Blueprint, jsonify, request

from core import checks, db, limits
from models import blacklist, entries, staff, visits
from routes import access, pages
from services import notify, whatsapp

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
    """A pass by its typed code, or by reference from the board. Reading records nothing.

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
    response = jsonify(expected=[board_row(v) for v in expected],
                       inside=[board_row(v) for v in inside], you=guard)
    # The page sends this tag back, and an unchanged board costs an empty 304. no-store: the
    # page keeps the board in memory, so no copy stays on a shared gate phone after Lock.
    response.headers["Cache-Control"] = "no-store"
    response.set_etag(pages.short_hash(response.get_data()))
    return response.make_conditional(request)


def board_row(visit):
    """A board row without the phone, marked when the number is on the blacklist."""
    row = {key: value for key, value in visit.items() if key != "phone"}
    return {**row, "blacklisted": blacklist.has(visit["phone"])}


@bp.post("/api/pass/<key>/<action>")
def gate_action(key, action):
    """Record an entry or exit with its own code. The reference is public, so it never records an
    entry. It records only the exit of a visitor inside, see exit_without_code()."""
    guard = access.gate_guard()
    if not guard:
        return jsonify(error="Wrong gate key"), 403
    if action not in NEEDS:
        return jsonify(error="Unknown action"), 404
    # A reference first: an old one, as VR-4022, also has the shape of a gate code.
    reference = whatsapp.normalize_reference(key)
    if reference and action == db.EXIT:
        return exit_without_code(reference, guard)

    code, visit, kind = by_typed_code(key)
    if visit is None:
        return jsonify(error="No pass has that code. Type the code on the visitor's pass."), 404
    why = refusal(visit, action, kind, code, guard)
    if why:
        return jsonify(error=why, visit=typed_pass(visit, code, kind)), 409
    done, no_photo = record_action(visit, action, guard)
    if no_photo:
        return jsonify(error=checks.NO_PHOTO, visit=typed_pass(visit, code, kind)), 400
    if done is None:
        fresh = visits.get(visit["reference"])
        # Still approved means the number joined the blacklist a moment ago.
        why = REFUSALS[action].get(fresh["status"], BLACKLISTED)
        return jsonify(error=why, visit=typed_pass(fresh, code, kind)), 409
    return jsonify(typed_pass(done, code, kind))


# Added to the guard's name on a visit let out without the exit code, for the admin page and log.
NO_EXIT_CODE = "(without the exit code)"
NOT_INSIDE = "Only a visitor who is inside now can be let out this way."


def exit_without_code(reference, guard):
    """The exit of a visitor who cannot show the exit code, such as a phone that died. An exit can
    let nobody in, so the reference from the Inside list is enough. Counted as a lookup."""
    if limits.too_many("pass-lookup", LOOKUPS_PER_MINUTE, 60, who=guard):
        return jsonify(error="Too many lookups. Wait a minute."), 429
    visit = visits.get(reference)
    if visit is None:
        return jsonify(error="No pass has that code. Type the code on the visitor's pass."), 404
    done = entries.check_out(reference, f"{guard} {NO_EXIT_CODE}")
    if done is None:
        return jsonify(error=NOT_INSIDE, visit=gate_view(visits.get(reference))), 409
    return jsonify(gate_view(done))


def by_typed_code(key):
    """(code, visit, kind) for a typed pass code. The visit is None when no pass has it."""
    code = whatsapp.normalize_gate_code(key)
    visit, kind = visits.by_code(code) if code else (None, None)
    return code, visit, kind


def record_action(visit, action, guard):
    """(visit after the entry or exit, True when the entry has no photo). The update itself
    decides, so two guards pressing at once never both win."""
    if action == db.EXIT:
        return entries.check_out(visit["reference"], guard), False
    # Read last, so a pass that cannot enter never asks for a photo.
    photo = checks.read_photo(request.get_json(silent=True))
    if photo is None:
        return None, True
    return entries.check_in(visit["reference"], guard, photo), False


def refusal(visit, action, kind, code, guard):
    """Why this code cannot do this action now, or None. A blacklisted number's stop is
    recorded too. The page and WhatsApp share it."""
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
# A scan is one call, so one guard can take 60 people a minute.
CODES_PER_MINUTE = 60
TOO_MANY_CODES = "Too many allow list codes in a minute. Wait a minute and try again."


def staff_view(person):
    """A person on the allow list as the gate sees them: name and code, never the number."""
    return {"code": person["code"], "name": person["name"], "tag": person["tag"],
            "blacklisted": blacklist.has(person["phone"])}


def staff_caller(code):
    """(guard, person, refusal) for an allow list call. Each call counts toward the limit, so a
    stolen gate key cannot try every code."""
    guard = access.gate_guard()
    if not guard:
        return None, None, (jsonify(error="Wrong gate key"), 403)
    if limits.too_many("allow-code", CODES_PER_MINUTE, 60, who=guard):
        return guard, None, (jsonify(error=TOO_MANY_CODES), 429)
    person = staff.by_code(staff.normalize_code(code) or "")
    if person is None:
        return guard, None, (jsonify(error=NO_SUCH_CODE), 404)
    return guard, person, None


@bp.get("/api/staff/<code>")
def read_staff(code):
    """A person on the allow list, by their 7-digit code. Records no entry."""
    guard, person, refused = staff_caller(code)
    if refused:
        return refused
    shown = staff_view(person)
    if shown["blacklisted"]:
        stopped_code(person, guard)
    return jsonify(shown)


# A scan is the toggle. In and out change a wrong scan, see staff.record_move().
STAFF_ACTIONS = {"scan": None, "in": db.ENTRY, "out": db.EXIT}
# A gate page opened before the toggle sends entry for every code, so it must reload.
OLD_PAGE = "This gate page is out of date. Reload the page, then type the code again."


@bp.post("/api/staff/<code>/<action>")
def staff_move(code, action):
    """Record an allow list entry or exit at once, see staff.record_move(). A new entry also
    sends the person a WhatsApp message. A blacklisted number cannot enter, but can leave."""
    guard, person, refused = staff_caller(code)
    if refused:
        return refused
    if action in NEEDS:
        return jsonify(error=OLD_PAGE), 409
    if action not in STAFF_ACTIONS:
        return jsonify(error="Unknown action"), 404
    shown = staff_view(person)
    kind, stamp, new, told = notify.staff_moved(person, guard, STAFF_ACTIONS[action],
                                                may_enter=not shown["blacklisted"])
    if stamp is None:
        stopped_code(person, guard)
        return jsonify(error=BLACKLISTED, **shown, kind=kind), 409
    return jsonify(**shown, kind=kind, at=stamp, new=new, told=told)

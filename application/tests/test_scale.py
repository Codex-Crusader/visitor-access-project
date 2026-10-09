"""How each call grows with the stored history: its SQL statements, the rows they examine, the
database pages they read, and the time the call takes, at two or more history sizes.

The history is what RETAIN_DAYS keeps: closed, expired and declined visits, staff moves, blocked
attempts and admin changes. The open part stays the same size: the requests that wait, the
gate board, today's staff moves. Every call starts with an empty read cache, the same as after
a change to the data.

A call on the gate, visitor, staff, WhatsApp or timer path must not grow with the history: the
same statements at every size, about the same rows examined, and no full read of a history
table. Pages are shown, not checked: an open row can sit alone on an old page, so the pages of
the open part also depend on where the rows happen to lie.

The admin search, the status counts and the downloads read every row by design: they must grow
no faster than the rows.

Run: .venv\\Scripts\\python.exe tests\\test_scale.py [sizes]
Sizes default to 2000,20000. The full run: tests\\test_scale.py 2000,20000,200000"""

import contextlib
import math
import os
import sys
import threading
import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg

# The kit comes first: it sets the settings and a clean database before the app loads.
from kit import ADMIN, APPROVER, JPEG, KEY, PHOTO, client, entry_of, exit_of, finish, inbound
from core import checks, config, db, limits
from models import blacklist, entries, people, visits
from services import export, timer, whatsapp

ALONE = __name__ == "__main__" and len(sys.argv) > 1
SIZES = [int(size) for size in (sys.argv[1] if ALONE else "2000,20000").split(",")]
# Set SCALE_DETAIL=1 to see the statements of each call that grows.
URL = os.environ["DATABASE_URL"]
# The real retention, so the history spreads over 90 days and the purge finds the old edge.
config.RETAIN_DAYS = 90
whatsapp.token_works = lambda: True
TIMED_RUNS = 5
HISTORY_TABLES = {"visits", "gate_codes", "photos", "staff_entries", "blocked_attempts",
                  "admin_changes"}
# A call that reads the history grows as n^1. A new plan on the open part can double the rows
# examined, as n^0.3 between the two largest sizes, and is still flat.
FLAT_GROWTH = 0.5
# A call that reads every row may grow this fast: linear, with some noise.
ROWS_GROWTH = 1.25


# --- Every SQL statement a call runs, from the thread that runs it ---

capture = threading.local()


def _recording(method):
    def record(self, query, params=None, *args, **kwargs):
        statements: list | None = getattr(capture, "statements", None)
        if statements is None:
            return method(self, query, params, *args, **kwargs)
        first = params[0] if method.__name__ == "executemany" and params else params
        statements.append((str(query), first))
        return method(self, query, params, *args, **kwargs)
    return record


for _method in ("execute", "executemany", "stream"):
    setattr(psycopg.Cursor, _method, _recording(getattr(psycopg.Cursor, _method)))


@contextlib.contextmanager
def recording():
    capture.statements = []
    try:
        yield capture.statements
    finally:
        capture.statements = None


# --- The rows and pages each statement reads, from EXPLAIN on its own connection ---

def plan_nodes(node):
    yield node
    for child in node.get("Plans", ()):
        yield from plan_nodes(child)


SCANS = ("Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan")


def rows_examined(node):
    """The rows a scan node looked at: the rows it returned and the rows that its filter
    dropped."""
    loops = node.get("Actual Loops", 1)
    return (node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0)
            + node.get("Rows Removed by Index Recheck", 0)) * loops


def read_by(conn, query, params):
    """{pages, rows, full} for one statement, rolled back, or None. full names each history
    table it reads whole."""
    if "pg_advisory" in query or not query.lstrip().upper().startswith(
            ("SELECT", "UPDATE", "DELETE", "INSERT", "WITH")):
        return None
    try:
        with conn.transaction(force_rollback=True):
            plan = conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query,
                                params).fetchone()[0][0]["Plan"]
    except psycopg.Error:
        return None
    nodes = list(plan_nodes(plan))
    return {
        "pages": plan.get("Shared Hit Blocks", 0) + plan.get("Shared Read Blocks", 0),
        "rows": sum(rows_examined(node) for node in nodes if node["Node Type"] in SCANS),
        "full": {node["Relation Name"] for node in nodes if node["Node Type"] == "Seq Scan"
                 and node.get("Relation Name") in HISTORY_TABLES},
    }


# --- The history and the open part ---

def stamp(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


CODE_LETTERS = visits.CODE_LETTERS
STATUSES = (db.CLOSED,) * 7 + (db.EXPIRED,) * 2 + (db.DECLINED,)
STAFF = 300


def history_code(number):
    """A gate code that starts with I or O, which a new code never does, so none clashes."""
    pair, digits = divmod(number, 10000)
    first, second = divmod(pair, len(CODE_LETTERS))
    return f"{'IO'[first]}{CODE_LETTERS[second]}-{digits:04d}"


# The psycopg types want a literal query. These are literals, split over lines.
# noinspection PyTypeChecker
def seed_history(count):
    """count old visits over 90 days, oldest first, with codes, photos and the other logs."""
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(days=89), now - timedelta(hours=config.PASS_HOURS + 2)
    step = (end - start) / count
    reasons = [reason for reason in config.REASONS if reason != config.OFFICE_REASON]
    with psycopg.connect(URL) as conn, conn.cursor() as cur:
        with cur.copy("COPY visits (reference, token, name, phone, address, reason, visiting,"
                      " guests, status, created_at, decided_at, decided_by, entered_at,"
                      " entered_by, exited_at, exited_by) FROM STDIN") as rows:
            for n in range(count):
                made = start + step * n
                status = STATUSES[n % len(STATUSES)]
                went = status == db.CLOSED
                rows.write_row((
                    f"H-{n}", f"history-token-{n}", f"Visitor {n}", f"98{n % 10 ** 8:08d}",
                    "1 Old Road", reasons[n % len(reasons)], f"S{n % 5000}", "[]", status,
                    stamp(made), stamp(made + timedelta(minutes=5)) if status != db.EXPIRED
                    else None, "main" if status != db.EXPIRED else None,
                    stamp(made + timedelta(hours=1)) if went else None,
                    "Gate desk (shared key)" if went else None,
                    stamp(made + timedelta(hours=3)) if went else None,
                    "Gate desk (shared key)" if went else None))
        with cur.copy("COPY gate_codes (code, reference, kind) FROM STDIN") as rows:
            for n in range(count):
                rows.write_row((history_code(2 * n), f"H-{n}", db.ENTRY))
                rows.write_row((history_code(2 * n + 1), f"H-{n}", db.EXIT))
        with cur.copy("COPY photos (reference, image, taken_at) FROM STDIN") as rows:
            for n in range(0, count, len(STATUSES)):
                rows.write_row((f"H-{n}", JPEG, stamp(start + step * n)))
        with cur.copy("COPY staff_entries (code, name, phone, entered_at, entered_by, kind)"
                      " FROM STDIN") as rows:
            for n in range(count):
                person = n % STAFF
                rows.write_row((str(1000000 + person), f"Staff {person}",
                                f"+9197{person:08d}", stamp(start + step * n), "Gate desk",
                                db.ENTRY if (n // STAFF) % 2 == 0 else db.EXIT))
        with cur.copy("COPY blocked_attempts (phone, name, what, detail, by_whom, at)"
                      " FROM STDIN") as rows:
            for n in range(count // 50):
                rows.write_row((f"+9196{n % 50:08d}", "Banned", blacklist.ASKED, "S1",
                                blacklist.VISITOR_PAGE, stamp(start + step * 50 * n)))
        with cur.copy("COPY admin_changes (at, by_whom, action, detail) FROM STDIN") as rows:
            for n in range(count // 50):
                rows.write_row((stamp(start + step * 50 * n), "Main admin", "Added a guard", ""))
        with cur.copy("COPY seen_messages (id, seen) FROM STDIN") as rows:
            for n in range(2000):
                rows.write_row((f"wamid.old.{n}", stamp(now - timedelta(minutes=n / 2))))


# noinspection PyTypeChecker
def seed_open_part():
    """The part that does not grow: allow list, blacklist, offices, guards, open requests,
    the gate board and today's staff moves. The same at every size."""
    with psycopg.connect(URL) as conn:
        conn.cursor().executemany(
            "INSERT INTO staff (code, name, phone, added_at, tag) VALUES (%s, %s, %s, %s, %s)",
            [(str(1000000 + n), f"Staff {n}", f"+9197{n:08d}", db.now(), f"Dept {n % 8}")
             for n in range(STAFF)])
        now = datetime.now(timezone.utc)
        conn.cursor().executemany(
            "INSERT INTO staff_entries (code, name, phone, entered_at, entered_by, kind)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            [(str(1000000 + n), f"Staff {n}", f"+9197{n:08d}",
              stamp(now - timedelta(minutes=600 - 3 * n)), "Gate desk", db.ENTRY)
             for n in range(150)])
    for n in range(50):
        blacklist.add(f"+9196{n:08d}", "Banned", "Test")
    for n in range(10):
        people.add_office(f"Office {n}", "+911234567890", "+911234567890")
    for n in range(10):
        people.add_holder(people.GUARDS, f"Guard {n}", f"+9198000{n:05d}")
    for _ in range(30):
        open_request()
    for _ in range(10):
        visits.mark_escalated(open_request()["reference"])
    for _ in range(40):
        approved_visit()
    for _ in range(20):
        inside_visit()


FORM = {"name": "Asha Rao", "phone": "9876543210", "address": "12 Park Road",
        "reason": "See a student", "visiting": "S1", "guests": ["Ravi Rao"]}


def open_request():
    return visits.create({key: FORM[key] for key in checks.FIELDS}, FORM["guests"])


def approved_visit():
    return visits.decide(open_request()["reference"], db.APPROVED, db.BY_MAIN)


def inside_visit():
    visit = approved_visit()
    return entries.check_in(visit["reference"], "Gate desk", JPEG)


def analyze():
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("VACUUM ANALYZE")


def fresh_database(size):
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    db.init()
    db.forget_cache()
    seed_history(size)
    seed_open_part()
    analyze()


# --- The calls. Each is (name, how it grows, prepare, call). prepare runs before the clock. ---

FLAT, ROWS = "flat", "rows"
HISTORY_TOKEN = "history-token-7"


def ok(response, *codes):
    assert response.status_code in (codes or (200,)), (response.status_code,
                                                        response.get_data(as_text=True)[:300])
    return response


def nothing():
    return None


def staff_code():
    """A person who has not moved for hours, so the scan is a new entry."""
    staff_code.n = getattr(staff_code, "n", 200) + 1
    return str(1000000 + staff_code.n % STAFF)


def webhook(text):
    return ok(client.post("/webhook/whatsapp", json=inbound(APPROVER, text)))


def owed_photo_dropped():
    """An approved pass, with no earlier photo owed: the approver's number is also the guard's."""
    entries.cancel_photo(APPROVER)
    return entry_of(approved_visit())


CALLS = [
    ("gate board", FLAT, nothing, lambda _: ok(client.get("/api/gate/board", headers=KEY))),
    ("pass by entry code", FLAT, lambda: entry_of(approved_visit()),
     lambda code: ok(client.get(f"/api/pass/{code}", headers=KEY))),
    ("pass by reference", FLAT, lambda: approved_visit()["reference"],
     lambda ref: ok(client.get(f"/api/pass/{ref}", headers=KEY))),
    ("visitor page, open pass", FLAT, lambda: approved_visit()["token"],
     lambda token: ok(client.get(f"/api/visit/{token}"))),
    ("visitor page, old pass", FLAT, nothing,
     lambda _: ok(client.get(f"/api/visit/{HISTORY_TOKEN}"))),
    ("new request", FLAT, nothing,
     lambda _: ok(client.post("/api/requests", json=FORM), 201)),
    ("entry with photo", FLAT, lambda: entry_of(approved_visit()),
     lambda code: ok(client.post(f"/api/pass/{code}/entry", headers=KEY, json=PHOTO))),
    ("exit", FLAT, lambda: exit_of(inside_visit()),
     lambda code: ok(client.post(f"/api/pass/{code}/exit", headers=KEY))),
    ("staff scan", FLAT, staff_code,
     lambda code: ok(client.post(f"/api/staff/{code}/scan", headers=KEY))),
    ("staff lookup", FLAT, staff_code,
     lambda code: ok(client.get(f"/api/staff/{code}", headers=KEY))),
    ("WhatsApp YES", FLAT, lambda: open_request()["reference"],
     lambda ref: webhook(f"YES {ref}")),
    ("WhatsApp reference", FLAT, lambda: open_request()["reference"],
     lambda ref: webhook(ref)),
    ("WhatsApp waiting list", FLAT, nothing, lambda _: webhook("hello")),
    ("WhatsApp IN", FLAT, owed_photo_dropped, lambda code: webhook(f"IN {code}")),
    ("timer round", FLAT, nothing, lambda _: timer_round()),
    ("admin first page", FLAT, nothing,
     lambda _: ok(client.get("/api/admin/visits", headers=ADMIN))),
    ("admin page, closed", FLAT, nothing,
     lambda _: ok(client.get("/api/admin/visits?status=closed", headers=ADMIN))),
    ("admin page, waiting", FLAT, nothing,
     lambda _: ok(client.get("/api/admin/visits?status=waiting", headers=ADMIN))),
    ("admin deep page", FLAT, lambda: middle_cursor(),
     lambda after: ok(client.get(f"/api/admin/visits?after={after}", headers=ADMIN))),
    ("admin deep page, closed", FLAT, lambda: middle_cursor(),
     lambda after: ok(client.get(f"/api/admin/visits?status=closed&after={after}",
                                 headers=ADMIN))),
    ("approve 10 at once", FLAT, lambda: [open_request()["reference"] for _ in range(10)],
     lambda refs: ok(client.post("/api/admin/decide", headers=ADMIN,
                                 json={"decision": "approve", "references": refs}))),
    ("add to blacklist", FLAT, lambda: f"+9195{staff_code():0>8}",
     lambda phone: ok(client.post("/api/admin/blacklist", headers=ADMIN,
                                  json={"phone": phone, "name": "X", "reason": "Test"}))),
    ("visitor settings", FLAT, nothing, lambda _: ok(client.get("/api/config"))),
    ("health", FLAT, nothing, lambda _: ok(client.get("/api/health"))),
    ("admin summary", ROWS, nothing, lambda _: ok(client.get("/api/admin/summary", headers=ADMIN))),
    ("admin search, rare", ROWS, nothing,
     lambda _: ok(client.get("/api/admin/visits?q=nobody-has-this", headers=ADMIN))),
    ("visit log CSV", ROWS, nothing, lambda _: download("/api/admin/export.csv")),
    ("staff log CSV", ROWS, nothing, lambda _: download("/api/admin/staff-entries.csv")),
    ("visit log ZIP", ROWS, nothing, lambda _: download("/api/admin/export.zip")),
]
# Each download as the server builds it. The test client would hold the whole answer.
DOWNLOADS = {
    "visit log CSV": lambda: export.csv_pieces(export.VISIT_COLUMNS, export.visit_rows()),
    "staff log CSV": export.staff_entries_csv,
    "visit log ZIP": export.zip_parts,
}


def download(path):
    """Read a download to its end, as the browser does. A streamed answer runs as it is read."""
    return len(ok(client.get(path, headers=ADMIN)).get_data())


def timer_round():
    timer.auto_approve_due()
    timer.escalate_due()
    visits.expire_old()
    visits.purge_old()
    timer.seconds_to_next_round()


def middle_cursor():
    with db.connect() as conn:
        row = conn.execute("SELECT created_at, reference FROM visits ORDER BY created_at"
                           " OFFSET (SELECT COUNT(*) / 2 FROM visits) LIMIT 1").fetchone()
    return f"{row['created_at']}|{row['reference']}"


def measure(call, explain: psycopg.Connection) -> dict[str, Any]:
    """{statements, rows, pages, full, ms, each} for one call. ms is the median time."""
    _name, kind, prepare, run = call
    times, counts, statements = [], [], []
    for _ in range(TIMED_RUNS if kind == FLAT else 2):
        prepared = prepare()
        limits.forget_hits()
        db.forget_cache()
        with recording() as seen:
            start = time.perf_counter()
            run(prepared)
            times.append((time.perf_counter() - start) * 1000)
        statements = statements or list(seen)
        counts.append(len(seen))
    # The fewest: a code that clashes by chance adds a try, and statements, to one run.
    found: dict[str, Any] = {"statements": min(counts), "rows": 0, "pages": 0, "full": set(),
                             "each": [], "ms": sorted(times)[len(times) // 2]}
    for query, params in statements:
        read = read_by(explain, query, params)
        if read:
            found["rows"] += read["rows"]
            found["pages"] += read["pages"]
            found["full"] |= read["full"]
            found["each"].append((read["rows"], read["pages"], " ".join(query.split())[:140]))
    return found


def growth(small, large, size_small, size_large):
    """The exponent k in large / small = (size_large / size_small) ** k."""
    return math.log((large + 1) / (small + 1)) / math.log(size_large / size_small)


def peak_memory(build):
    """The most Python memory a download holds at once, in MB, as each piece goes out."""
    db.forget_cache()
    tracemalloc.start()
    try:
        for _piece in build():
            pass
        return tracemalloc.get_traced_memory()[1] / 1e6
    finally:
        tracemalloc.stop()


def measure_sizes():
    """(results, memory) for every call and every download at every size."""
    results, memory = {}, {}
    for size in SIZES:
        print(f"\n--- {size} visits of history", flush=True)
        began = time.perf_counter()
        fresh_database(size)
        print(f"  seeded in {time.perf_counter() - began:.1f} s", flush=True)
        with psycopg.connect(URL) as explain_conn:
            for call in CALLS:
                results[(call[0], size)] = measure(call, explain_conn)
        for name, build in DOWNLOADS.items():
            memory[(name, size)] = peak_memory(build)
    return results, memory


def problems_of(name, kind, results, k_rows):
    """Why this call grows faster than it may, as a list. Empty when it does not."""
    last = results[(name, SIZES[-1])]
    if kind == ROWS:
        return ([f"{name}: rows examined grow as n^{k_rows:.2f}, faster than the rows"]
                if k_rows > ROWS_GROWTH else [])
    problems = []
    counts = sorted({results[(name, size)]["statements"] for size in SIZES})
    if len(counts) > 1:
        problems.append(f"{name}: {counts} statements at the sizes")
    if k_rows > FLAT_GROWTH:
        problems.append(f"{name}: rows examined grow as n^{k_rows:.2f}")
    if last["full"]:
        problems.append(f"{name}: reads all of {', '.join(sorted(last['full']))}")
    return problems


def report(results):
    """Print one line per call. Growth is between the two largest sizes: at the smallest, a
    whole table fits in a few pages. Returns the problems."""
    small, large = SIZES[-2], SIZES[-1]
    head = "".join(f"{size:>8}" for size in SIZES)
    print(f"\n{'call':<25}{'grows':>6}{'SQL':>5}   rows at{head}{'k':>6}"
          f"{'pages':>8}{'k':>6}{'ms':>8}{'k':>6}")
    problems = []
    for name, kind, _, _ in CALLS:
        at, last = results[(name, small)], results[(name, large)]
        k_rows, k_pages, k_ms = (growth(at[what], last[what], small, large)
                                 for what in ("rows", "pages", "ms"))
        rows = "".join(f"{results[(name, size)]['rows']:>8}" for size in SIZES)
        print(f"{name:<25}{kind:>6}{last['statements']:>5}{'':>10}{rows}{k_rows:>6.2f}"
              f"{last['pages']:>8}{k_pages:>6.2f}{last['ms']:>8.1f}{k_ms:>6.2f}"
              + (f"  reads all of {', '.join(sorted(last['full']))}" if last["full"] else ""))
        problems += problems_of(name, kind, results, k_rows)
    return problems


def main():
    """Measure every call at every size, print the table, and fail on a flat call that grows."""
    results, memory = measure_sizes()
    problems = report(results)
    print("\nThe most memory a download holds at once, MB:")
    for name in sorted(DOWNLOADS):
        sizes = "  ".join(f"{size}: {memory[(name, size)]:.1f}" for size in SIZES)
        print(f"  {name:<16}{sizes}")
    if os.getenv("SCALE_DETAIL"):
        for name in {problem.split(":")[0] for problem in problems}:
            show_growth(name, results)
    assert not problems, "\n".join(problems)
    print("\nevery gate, visitor, staff, WhatsApp and timer call stays flat as the history grows")


def show_growth(name, results):
    """Each statement of one call at the two largest sizes, with its rows and pages."""
    for size in SIZES[-2:]:
        print(f"  {name} at {size}:")
        for rows, pages, query in results[(name, size)]["each"]:
            print(f"    {rows:>7} {pages:>6}  {query}")


if __name__ == "__main__":
    main()
    finish()

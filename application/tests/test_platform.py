"""Pages, headers, health, the timer, the cache and the database connection.

Run: .venv\\Scripts\\python.exe tests\\test_platform.py"""

import ast
import contextlib
import os
import psycopg
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from psycopg_pool import PoolTimeout

# The kit comes first: it sets the settings and a clean database before the app loads.
from kit import (
    APPROVER, APP_DIR, KEY, PHOTO, approved, client, entry_of, exit_of,
    finish, new_request, say,
)
import app as application
from core import config
from core import db
from core import limits
from core import migrations
from routes import pages
from models import people
from services import timer
from models import visits
from services import whatsapp

print("pages are served")
for path in ("/", "/visitor.js", "/gate", "/gate.js", "/admin", "/admin.js", "/shared.js",
             "/sw.js"):
    assert client.get(path).status_code == 200, path

print("every answer carries the security headers")
page_answer = client.get("/admin")
not_changed = client.get("/admin", headers={"If-None-Match": page_answer.headers["ETag"]})
assert not_changed.status_code == 304
script_tag = re.search(r'src="(admin\.js\?v=\w+)"', page_answer.get_data(as_text=True))
assert script_tag, "the admin page loads its script by version"
script_path = script_tag[1]
for answer in (page_answer, not_changed, client.get("/" + script_path),
               client.get("/api/config"), client.get("/api/visit/nope"),
               client.get("/api/admin/visits")):
    for name, value in pages.SECURITY_HEADERS.items():
        strict = name == "Content-Security-Policy" and answer in (page_answer, not_changed)
        expected = pages.STRICT_POLICY if strict else value
        assert answer.headers.get(name) == expected, (answer.status_code, name)
assert "unsafe-inline" not in pages.STRICT_POLICY and "script-src 'self';" in pages.STRICT_POLICY
assert client.get("/").headers["Content-Security-Policy"] == pages.CONTENT_POLICY
style_tag = re.search(r'href="(admin\.css\?v=\w+)"', page_answer.get_data(as_text=True))
assert style_tag, "the admin page loads its styles by version"
styles = client.get("/" + style_tag[1])
assert styles.status_code == 200 and "immutable" in styles.headers["Cache-Control"]
policy = pages.CONTENT_POLICY
assert "frame-ancestors 'self'" in policy and "object-src 'none'" in policy
assert "img-src 'self' data:" in policy, "the logo is a data: image"
print("  page, 304, script, API, 404 and 403 all carry them")

print("the health check names what failed and never why")
meta_calls = []
real_token_works = whatsapp.token_works
whatsapp.token_works = lambda: meta_calls.append(1) or True
application.forget_meta_check()
healthy = client.get("/api/health")
assert healthy.status_code == 200 and healthy.get_json() == {"database": True, "whatsapp": True}
assert client.get("/api/health").status_code == 200
assert len(meta_calls) == 1, "Meta is asked at most once an hour"
whatsapp.token_works = lambda: meta_calls.append(1) or False
application.forget_meta_check()
expired_token = client.get("/api/health")
assert expired_token.status_code == 503
assert expired_token.get_json() == {"database": True, "whatsapp": False}, "no reason, no token"
client.get("/api/health")
assert len(meta_calls) == 2, "a failure is asked again after 5 minutes, not at once"
application.forget_meta_check()
real_ping = db.ping
db.ping = lambda: False
whatsapp.token_works = lambda: True
assert client.get("/api/health").get_json() == {"database": False, "whatsapp": True}
db.ping = real_ping
whatsapp.token_works = real_token_works
assert db.ping() is True
# The real check, with Meta's answers stubbed: an expired token and a lost connection.
real_get = whatsapp.requests.get
whatsapp.requests.get = lambda *_a, **_k: type("R", (), {"ok": False, "status_code": 401})()
assert whatsapp.token_works() is False


def no_network(*_args, **_kwargs):
    raise whatsapp.requests.ConnectionError("down")


whatsapp.requests.get = no_network
assert whatsapp.token_works() is False
whatsapp.requests.get = lambda *_a, **_k: type("R", (), {"ok": True, "status_code": 200})()
assert whatsapp.token_works() is True
whatsapp.requests.get = real_get
limits.forget_hits()
print("  200 when both work, 503 with the failed part, Meta asked once an hour")

print("the timer sleeps until the next deadline")
real_next_due = visits.next_due
moment = datetime.now(timezone.utc)
for due, low, high in ((None, 3600, 3600),
                       (moment + timedelta(minutes=10), 590, 602),
                       (moment - timedelta(minutes=5), 30, 30),
                       (moment + timedelta(hours=5), 3600, 3600)):
    visits.next_due = lambda when=due: when
    wait = timer.seconds_to_next_round()
    assert low <= wait <= high, (due, wait)
visits.next_due = real_next_due
timer.wake.clear()
soon = new_request()
assert timer.wake.is_set(), "a new request wakes the timer"
due = visits.next_due()
made = datetime.fromisoformat(soon["created_at"])
assert due is not None and due <= made + timedelta(minutes=config.ESCALATE_MINUTES), due
print("  idle an hour, a deadline on time, overdue in 30 seconds, a new request wakes it")
cfg = client.get("/api/config").get_json()
assert cfg["escalate_minutes"] == 30 and cfg["retain_days"] == 1
assert "gate_key" not in str(cfg).lower(), "the gate key must never be published"

print("migrations run once, so a restart keeps every visit")
kept_visit = new_request()
assert db.init() == len(migrations.MIGRATIONS)
assert db.init() == len(migrations.MIGRATIONS)
with db.connect() as conn:
    versions = [row["version"] for row in
                conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
assert versions == list(range(1, len(migrations.MIGRATIONS) + 1)), versions
assert visits.get(kept_visit["reference"]) is not None
# A step added later runs on the next start, and the visits stay.
migrations.MIGRATIONS.append("ALTER TABLE visits ADD COLUMN test_note TEXT")
try:
    assert db.init() == len(migrations.MIGRATIONS)
    assert visits.get(kept_visit["reference"])["test_note"] is None
finally:
    migrations.MIGRATIONS.pop()
print(f"  schema at version {len(migrations.MIGRATIONS)}, a new column added, visits kept")

print("scripts are cached by version, pages are checked")
for path, script in (("/", "visitor.js"), ("/gate", "gate.js"), ("/admin", "admin.js")):
    shown = client.get(path)
    assert shown.headers["Cache-Control"] == "no-cache", shown.headers
    address = f"{script}?v={pages.SCRIPT_VERSIONS[script]}"
    assert address in shown.get_data(as_text=True), path
    kept = client.get("/" + address)
    assert kept.status_code == 200
    assert "immutable" in kept.headers["Cache-Control"], kept.headers
    # A wrong or missing version is never kept, so no address can hold stale code.
    for other in (f"/{script}", f"/{script}?v=old"):
        assert "immutable" not in client.get(other).headers.get("Cache-Control", ""), other
    again = client.get(path, headers={"If-None-Match": shown.headers["ETag"]})
    assert again.status_code == 304 and not again.data, path
# The service worker is checked on every load, or a phone could keep an old one.
worker = client.get("/sw.js")
assert worker.status_code == 200 and "immutable" not in worker.headers.get("Cache-Control", "")
print("  3 pages: 304 when unchanged, each script kept for a year under its hash")

print("each request makes as few database trips as it can")
real_connect, trips = db.connect, []
db.connect = lambda: trips.append(1) or real_connect()
try:
    counted = new_request()
    say(APPROVER, f"YES {counted['reference']}")
    counted_code = entry_of(counted)
    for label, call, most in (
        ("status check", lambda: client.get(f"/api/visit/{counted['token']}"), 1),
        # 2: the pass, and the blacklist, which stays in memory until the next write.
        ("pass lookup", lambda: client.get(f"/api/pass/{counted_code}", headers=KEY), 2),
        ("entry", lambda: client.post(f"/api/pass/{counted_code}/entry",
                                      headers=KEY, json=PHOTO), 2),
    ):
        trips.clear()
        assert call().status_code == 200, label
        assert len(trips) <= most, (label, len(trips))

    # Repeated page reads cost no database trip until the data changes.
    # A visitor on the board, so a board read also checks the blacklist.
    approved()
    ravi_key = people.add_holder(people.GUARDS, "Cache Guard", "+919800000777")
    status = lambda: client.get(f"/api/visit/{counted['token']}")  # noqa: E731
    gate_board = lambda: client.get("/api/gate/board", headers={"X-Gate-Key": ravi_key})  # noqa: E731
    for label, call in (("status check", status), ("board with a guard's key", gate_board)):
        call()
        trips.clear()
        assert call().status_code == 200 and len(trips) == 0, (label, len(trips))
    # Each WhatsApp message and each new request reads the approvers. They stay in memory too.
    people.approver_table()
    trips.clear()
    assert people.approver_table()["reasons"] and len(trips) == 0, len(trips)
    # The gate page sends the board's tag back. An unchanged board is an empty 304.
    board_tag = gate_board().headers["ETag"]
    unchanged = client.get("/api/gate/board",
                           headers={"X-Gate-Key": ravi_key, "If-None-Match": board_tag})
    assert unchanged.status_code == 304 and not unchanged.data, unchanged.status_code
    assert gate_board().headers["Cache-Control"] == "no-store"
    # A write makes them stale, so the next read goes to the database once.
    exit_code = exit_of(counted)
    client.post(f"/api/pass/{exit_code}/exit", headers=KEY)
    trips.clear()
    assert status().get_json()["status"] == "closed", "a write is seen at once"
    assert len(trips) == 1, len(trips)
    trips.clear()
    # Every write clears the whole cache, so the guard list and the blacklist are read again too.
    assert gate_board().status_code == 200 and len(trips) == 3, len(trips)
    people.remove_holder(people.GUARDS, "+919800000777")
    # An unknown token is never kept, so a scanner cannot fill the memory.
    for _ in range(2):
        trips.clear()
        assert client.get("/api/visit/not-a-token").status_code == 404
        assert len(trips) == 1, len(trips)
    # In the first minutes after start, the old version may still write, so nothing is kept.
    db.CACHE_AFTER_SECONDS = 10**9
    try:
        status()
        trips.clear()
        status()
        assert len(trips) == 1, "nothing is kept while the server is new"
    finally:
        db.CACHE_AFTER_SECONDS = 0
finally:
    db.connect = real_connect
print("  status check 1, pass lookup 1, entry 2; a repeated poll 0 until the next write")

print("each folder imports only from the folders before it")
LAYERS = ("core", "models", "services", "routes")
backwards = []
for rank, folder in enumerate(LAYERS):
    for source in Path(APP_DIR, folder).glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module in LAYERS[rank + 1:]:
                backwards.append(f"{folder}/{source.name} imports {node.module}")
assert not backwards, backwards
print("  core, then models, then services, then routes")

print("every write to a cached table clears the cache")
# A new write function that forgets @writes fails here, not as stale pages later.
# {table} is the guards or admins table in people.py.
CACHED_TABLES = re.compile(
    r"\b(INSERT INTO|UPDATE|DELETE FROM)\s+"
    r"((visits|guards|admins|offices|approvers|reason_auto|staff|blacklist|photos|gate_codes)\b"
    r"|\{table})")
forgot = []
for module in ("core/db.py", "models/visits.py", "models/entries.py", "models/people.py",
               "models/staff.py", "models/blacklist.py", "models/tags.py"):
    with open(os.path.join(APP_DIR, module),
              encoding="utf-8") as db_file:
        db_source = db_file.read()
    for node in ast.parse(db_source).body:
        if isinstance(node, ast.FunctionDef) and node.name != "migrate":
            # @writes in db.py, @db.writes in the others.
            names = [getattr(d, "id", "") or getattr(d, "attr", "") for d in node.decorator_list]
            body = ast.get_source_segment(db_source, node) or ""
            if CACHED_TABLES.search(body) and "writes" not in names:
                forgot.append(f"{module}: {node.name}")
assert not forgot, f"these change cached tables without @writes: {forgot}"
print("  every function that changes a cached table has @writes")

print("a dropped connection is retried for reads, never for writes")
tries = []


@db.read
def flaky_read():
    tries.append(1)
    if len(tries) == 1:
        raise psycopg.OperationalError("server closed the connection")
    return "read"


assert flaky_read() == "read" and len(tries) == 2


@db.read
def full_pool():
    tries.append(1)
    raise PoolTimeout("no connection")


tries.clear()
with contextlib.suppress(PoolTimeout):
    full_pool()
assert len(tries) == 1, "a full pool must not be waited on twice"

# The server ends every connection in the pool. The next read still works.
kept_visit = new_request()
with psycopg.connect(config.DATABASE_URL, autocommit=True) as killer:
    killer.execute("""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                      WHERE pid <> pg_backend_pid() AND datname = current_database()""")
assert visits.get(kept_visit["reference"])["reference"] == kept_visit["reference"]

# At start, a database that is still waking is tried again before giving up.
real_migrate, real_waits = db.migrate, db.START_WAITS
db.START_WAITS = (0, 0, 0, 0)
fails = []


def waking():
    if len(fails) < 3:
        fails.append(1)
        raise psycopg.OperationalError("the database system is starting up")
    return real_migrate()


def never_up():
    raise psycopg.OperationalError("the database is down")


db.migrate = waking
try:
    assert db.init() == len(migrations.MIGRATIONS) and len(fails) == 3
    db.migrate = never_up
    try:
        db.init()
        raise AssertionError("a database that never answers must stop the start")
    except psycopg.OperationalError:
        pass
finally:
    db.migrate, db.START_WAITS = real_migrate, real_waits
print("  retried after a drop, a full pool fails at once, the start waits for the database")

print("on exit, the timer stops and the database closes before Python shuts down")
overdue = new_request()
with db.connect() as conn:
    conn.execute("UPDATE visits SET auto_approve_at = %s WHERE reference = %s",
                 ("2020-01-01T00:00:00+00:00", overdue["reference"]))
db.forget_cache()
application.start_background()
assert timer.background.is_alive()
# The first round runs at once, so a request due while the server slept is approved on wake.
for _ in range(50):
    if visits.get(overdue["reference"])["status"] == "approved":
        break
    timer.stopping.wait(0.1)
assert visits.get(overdue["reference"])["status"] == "approved", "the first round must not wait"
started = time.monotonic()
application.stop_background()
assert time.monotonic() - started < 3, "exit must not wait out the timer's sleep"
application.stop_background()
assert not timer.background.is_alive(), "the timer must stop"
try:
    db.connect()
    raise AssertionError("a closed database must not open a new pool on the way out")
except RuntimeError:
    pass
print("  timer stopped, pool closed, safe to call twice")

print()

finish()

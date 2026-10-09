"""A busy campus, ten times faster than real use, with Meta and the database failing on purpose.

Every call goes through the server's threads, as in gunicorn, so a call waits its turn as on
the server. The timer runs. Each phase prints, for each call, the time from the press to the answer
(p50, p95, p99, max) and the failures. At the end, the data must be right: no request made
twice, no visitor let in twice, the timer still running, and the server answering again.

Run: .venv\\Scripts\\python.exe tests\\load.py [seconds per phase]   Default: 30.
LOAD_THREADS sets the server's threads, 8 by default, as --threads in render.yaml. LANES sets
the gate lanes that scan staff codes, 4 by default."""

import contextlib
import itertools
import os
import random
import sys
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType

import psycopg

import test_scale as scale
from kit import ADMIN, APPROVER, KEY, PHOTO, client, entry_of, exit_of, finish
import app as application
from core import config, db, limits
from routes import gate
from services import timer, whatsapp

PHASE_SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 30
SPEED = 10
HISTORY = 18000
# A WhatsApp send that works, and one that hangs until the 15 s timeout.
META_FAST, META_HUNG = 0.3, whatsapp.TIMEOUT_SECONDS
# The visitor page gives up on a status check after this, see POLL_TIMEOUT in visitor.js.
VISITOR_GIVES_UP = 10.0

meta = {"seconds": META_FAST}
lock = threading.Lock()


def slow_send(*_args, **_kwargs):
    """Stands in for a WhatsApp send. It takes Meta's time, and a hang ends as in requests."""
    seconds = meta["seconds"]
    time.sleep(seconds)
    if seconds >= META_HUNG:
        raise whatsapp.Uncertain(f"No answer from WhatsApp in {seconds:.0f} s")
    return {}


whatsapp.send = slow_send
whatsapp.send_template = slow_send

# This run tests load, not the limits that stop one caller.
config.REQUESTS_PER_HOUR = config.REQUESTS_PER_HOUR_ALL = 10 ** 9
gate.CODES_PER_MINUTE = gate.LOOKUPS_PER_MINUTE = 10 ** 9
# Reminders and the timer's rounds come within the run.
config.ESCALATE_MINUTES = 1
timer.BACKGROUND_SECONDS = 2

THREADS = int(os.getenv("LOAD_THREADS", "8"))
LANES = int(os.getenv("LANES", "4"))
# The threads of the one gunicorn worker.
server = ThreadPoolExecutor(max_workers=THREADS)


class Record:
    """Each call's times and failures, per phase."""

    def __init__(self):
        self.phase = "start"
        self.times: dict[tuple[str, str], list[float]] = {}
        self.failures: dict[tuple[str, str], int] = {}

    def add(self, name, seconds, failed):
        with lock:
            key = (self.phase, name)
            self.times.setdefault(key, []).append(seconds)
            if failed:
                self.failures[key] = self.failures.get(key, 0) + 1


record = Record()


class NoAnswer:
    """What call() gives back when the app raised an error instead of answering."""
    status_code = 599
    headers = MappingProxyType({})

    @staticmethod
    def get_json():
        return {}


def call(name, how, *args, **kwargs):
    """Send one call through the server's threads and wait, as a phone does."""
    start = time.perf_counter()
    # noinspection PyBroadException
    try:
        answer = server.submit(how, *args, **kwargs).result()
        failed = answer.status_code >= 500
    except Exception:  # an error the app did not turn into an answer
        answer, failed = NoAnswer(), True
    record.add(name, time.perf_counter() - start, failed)
    return answer


running = threading.Event()
tokens, approved_codes, inside_codes = [], [], []
made, entered = [], []


def every(seconds, job):
    """Run job again and again, real seconds / SPEED apart, while the run lasts."""
    def loop():
        while running.is_set():
            # The test's own lookup of a code can fail while the database is down.
            with contextlib.suppress(psycopg.Error):
                job()
            time.sleep(seconds / SPEED * random.uniform(0.5, 1.5))
    return threading.Thread(target=loop, daemon=True)


def gate_page():
    tag = {}

    def poll():
        answer = call("gate board", client.get, "/api/gate/board",
                      headers={**KEY, **({"If-None-Match": tag["at"]} if tag else {})})
        if answer.status_code == 200:
            tag["at"] = answer.headers["ETag"]
    return poll


def visitor_page():
    with lock:
        token = random.choice(tokens) if tokens else None
    if token:
        call("visitor page", client.get, f"/api/visit/{token}")


def admin_page():
    call("admin summary", client.get, "/api/admin/summary", headers=ADMIN)
    call("admin visits", client.get, "/api/admin/visits", headers=ADMIN)


FORM = {**scale.FORM}
form_keys = itertools.count()


def new_visitor():
    answer = call("new request", client.post, "/api/requests",
                  json={**FORM, "request_key": f"load-{next(form_keys):012d}xxxx"})
    if answer.status_code != 201:
        return
    visit = answer.get_json()
    with lock:
        tokens.append(visit["token"])
        made.append(visit["reference"])
    approve(visit["reference"])


message_ids = itertools.count()


def inbound(sender, text):
    """A Meta webhook message with its own id. next() on a count is safe across threads."""
    return {"entry": [{"changes": [{"value": {"messages": [
        {"id": f"wamid.load.{next(message_ids)}", "from": sender, "type": "text",
         "text": {"body": text}}]}}]}]}


def approve(reference):
    """The approver answers YES on WhatsApp. The guard then sees the pass."""
    message = inbound(APPROVER, f"YES {reference}")
    call("WhatsApp YES", client.post, "/webhook/whatsapp", json=message)
    code = entry_of({"reference": reference})
    with lock:
        approved_codes.append(code)


def guard_entry():
    with lock:
        code = approved_codes.pop(0) if approved_codes else None
    if not code:
        return
    answer = call("entry", client.post, f"/api/pass/{code}/entry", headers=KEY, json=PHOTO)
    if answer.status_code != 200:
        return
    reference = answer.get_json()["reference"]
    with lock:
        entered.append(reference)
        inside_codes.append(exit_of({"reference": reference}))


def guard_exit():
    with lock:
        code = inside_codes.pop(0) if len(inside_codes) > 5 else None
    if code:
        call("exit", client.post, f"/api/pass/{code}/exit", headers=KEY)


def staff_scan():
    code = str(1000000 + random.randrange(scale.STAFF))
    call("staff scan", client.post, f"/api/staff/{code}/scan", headers=KEY)


def whatsapp_lookup():
    with lock:
        code = random.choice(approved_codes) if approved_codes else None
    if code:
        call("WhatsApp lookup", client.post, "/webhook/whatsapp", json=inbound(APPROVER, code))


def health():
    limits.forget_hits()
    call("health", client.get, "/api/health")


def users():
    """Three gate pages, twenty visitor pages, one admin page, the gate lanes and the people at
    the gate."""
    return [
        *(every(30, gate_page()) for _ in range(3)),
        *(every(5, visitor_page) for _ in range(20)),
        every(60, admin_page),
        every(12, new_visitor),
        every(15, guard_entry),
        every(30, guard_exit),
        *(every(4, staff_scan) for _ in range(LANES)),
        every(20, whatsapp_lookup),
        every(10, health),
    ]


# --- The database failing ---

# The psycopg types want a literal query. This is one, split over two lines.
# noinspection PyTypeChecker
def drop_connections():
    """Close every app connection on the server side, as Neon does when it restarts."""
    with psycopg.connect(scale.URL, autocommit=True) as conn:
        dropped, = conn.execute(
            "SELECT COUNT(pg_terminate_backend(pid)) FROM pg_stat_activity"
            " WHERE pid <> pg_backend_pid() AND datname = current_database()"
        ).fetchone() or (0,)
    return dropped


real_connect = psycopg.Connection.connect


def refuse_connections(seconds):
    """No new connection opens for this long, as while Neon wakes."""
    until = time.monotonic() + seconds

    def connect(_cls, *args, **kwargs):
        if time.monotonic() < until:
            raise psycopg.OperationalError("connection refused: the database is waking")
        return real_connect(*args, **kwargs)
    psycopg.Connection.connect = classmethod(connect)


def database_down():
    """Drop every connection, and open no new one for 5 s."""
    refuse_connections(5)
    drop_connections()


def percentile(times, share):
    """The time, in ms, that this share of the sorted times is at or under."""
    return times[min(len(times) - 1, int(share * len(times)))] * 1000


def report(label):
    names = sorted({name for p, name in record.times if p == label})
    print(f"\n{label}")
    print(f"  {'call':<17}{'calls':>6}{'p50 ms':>9}{'p95 ms':>9}{'p99 ms':>9}{'max ms':>9}"
          f"{'failed':>8}")
    for name in names:
        times = sorted(record.times[(label, name)])
        shares = "".join(f"{percentile(times, share):>9.0f}" for share in (0.5, 0.95, 0.99))
        print(f"  {name:<17}{len(times):>6}{shares}{times[-1] * 1000:>9.0f}"
              f"{record.failures.get((label, name), 0):>8}")


def phase(name, seconds, before=None):
    record.phase = name
    if before:
        before()
    time.sleep(seconds)
    report(name)


def main():
    print(f"{THREADS} server threads, {LANES} gate lanes. Seeding {HISTORY} visits of history",
          flush=True)
    scale.fresh_database(HISTORY)
    application.start_background()
    tracemalloc.start()
    running.set()
    people = users()
    for person in people:
        person.start()

    phase("warm up", PHASE_SECONDS / 3)
    memory_at_start = tracemalloc.get_traced_memory()[0]
    phase("normal, Meta answers in 0.3 s", PHASE_SECONDS)
    phase("Meta hangs for 15 s on every send", PHASE_SECONDS,
          before=lambda: meta.update(seconds=META_HUNG))
    phase("Meta works again", PHASE_SECONDS, before=lambda: meta.update(seconds=META_FAST))
    phase("every database connection dropped", PHASE_SECONDS,
          before=lambda: print(f"\n  dropped {drop_connections()} connections"))
    phase("no new database connection for 5 s", PHASE_SECONDS,
          before=database_down)
    phase("after the faults", PHASE_SECONDS)

    running.clear()
    for person in people:
        person.join()
    server.shutdown(wait=True)
    grown = (tracemalloc.get_traced_memory()[0] - memory_at_start) / 1e6
    tracemalloc.stop()
    check_the_data(grown)


def check_the_data(grown):
    print("\nthe data after the run")
    with db.connect() as conn:
        kept = {row["reference"]: row for row in conn.execute(
            "SELECT reference, status, entered_at, request_key FROM visits"
            " WHERE reference = ANY(%s)", (made,)).fetchall()}
        keys = conn.execute("SELECT COUNT(*) AS n, COUNT(DISTINCT request_key) AS distinct_keys"
                            " FROM visits WHERE request_key LIKE 'load-%%'").fetchone()
    print(f"  {len(made)} requests made, {len(kept)} kept, {keys['n']} with a load key")
    assert keys["n"] == keys["distinct_keys"], "a request was made twice"
    assert len(entered) == len(set(entered)), "a visitor was let in twice"
    assert all(kept[ref]["entered_at"] for ref in entered if ref in kept), "an entry was lost"
    print(f"  {len(entered)} entries, each once")
    assert timer.background.is_alive(), "the timer stopped"
    print("  the timer still runs")
    limits.forget_hits()
    health_now = client.get("/api/health")
    assert health_now.status_code == 200, health_now.get_json()
    print("  the health check answers 200")
    # noinspection PyProtectedMember
    print(f"  memory grew {grown:.1f} MB in the run. Cache entries: {len(db._cache)},"
          f" rate limit callers: {limits.hit_buckets()}, threads: {threading.active_count()}")


if __name__ == "__main__":
    main()
    finish()
    print("load run done")

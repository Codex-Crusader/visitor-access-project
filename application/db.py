"""The Postgres connection, the schema steps, the read cache, and the stored values.

The connection string comes from DATABASE_URL. Connections come from a small
pool, because opening a new one to a hosted database takes far longer than
the query itself. The queries live in visits.py, entries.py and people.py.
"""

import atexit
import copy
import functools
import logging
import threading
import time
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg import OperationalError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

import config
import migrations

PENDING = "pending"
ESCALATED = "escalated"
APPROVED = "approved"
DECLINED = "declined"
INSIDE = "inside"
CLOSED = "closed"
# Not approved and not used within PASS_HOURS of the request.
EXPIRED = "expired"
OPEN_STATUSES = (PENDING, ESCALATED)
# The statuses that turn to EXPIRED once PASS_HOURS have passed.
EXPIRING = (PENDING, ESCALATED, APPROVED)

# The two kinds of gate code.
ENTRY = "entry"
EXIT = "exit"

# Values of decided_by.
BY_MAIN = "main"
BY_BACKUP = "backup"
BY_AUTO = "auto"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


# The open pool, or none yet. A list, so its type is never None.
_pools: list[ConnectionPool] = []
_pool_lock = threading.Lock()
_closed = False


def connect() -> AbstractContextManager[Any]:
    """A pooled connection, as a with block that commits at the end.

    An error inside the block rolls everything in it back. The pool opens on
    first use, so importing this module never touches the network.

    prepare_threshold=None turns off prepared statements, which a pooled
    connection string (Neon's -pooler host) cannot keep between transactions.
    The check sends a quick query before handing out a connection, because
    Neon closes idle connections when it scales to zero.

    The connection is typed Any on purpose. The psycopg hints accept only a
    literal string as a query, and the queries here are built from constants
    in this file, never from input. Input always goes in the parameters.
    """
    with _pool_lock:
        if _closed:
            raise RuntimeError("The database is closed: the app is shutting down")
        if not _pools:
            _pools.append(ConnectionPool(
                config.DATABASE_URL,
                # The four gunicorn threads, plus the background loop. Two stay
                # open, so the timer and a request never wait for a new one.
                min_size=2,
                max_size=5,
                # A request waits at most 5 seconds for a connection. The same
                # four threads serve the pages, so a slow database must not
                # hold them long. The visitor page gives up at 10 seconds.
                timeout=5,
                # A connection attempt that hangs fails after 10 seconds and
                # is tried again, instead of holding a waiting request forever.
                # Keepalives notice a connection that died without a word in
                # about a minute, not the two hours the system waits by default.
                kwargs={
                    "row_factory": dict_row,
                    "prepare_threshold": None,
                    "connect_timeout": 10,
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 3,
                },
                check=ConnectionPool.check_connection,
                open=True,
            ))
    return _pools[0].connection()


def close():
    """Close the pool and its helper threads. Safe to call more than once.

    Call it before the process exits. A pool left open is closed by Python's
    own cleanup during interpreter shutdown, when Python 3.14 can no longer
    join its threads: the connections are dropped instead of closed, and the
    log shows PythonFinalizationError. After close(), connect() refuses, so
    nothing opens a new pool on the way out.
    """
    global _closed
    with _pool_lock:
        _closed = True
        closing = _pools[:]
        _pools.clear()
    for pool in closing:
        pool.close(timeout=5)


# Scripts and tests that open the database close it on exit too. The app
# itself stops its timer first, see app.stop_background().
atexit.register(close)

log = logging.getLogger(__name__)

# Seconds to wait before each new try when the database cannot be reached at
# start. Neon takes a moment to wake, and gunicorn stops the whole server when
# its worker fails to start, so the start waits about 15 seconds before it
# gives up.
START_WAITS = (1, 2, 4, 8)


def init():
    """Run every migration this database has not run yet. Returns the version.

    A connection that fails is tried again after each of START_WAITS.
    """
    for wait in START_WAITS:
        try:
            return migrate()
        except OperationalError as failure:
            log.warning("Database not reachable at start, again in %ss: %s", wait, failure)
            time.sleep(wait)
    return migrate()


def migrate():
    """One attempt at init(): run the migrations that are new to this database."""
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (migrations.MIGRATION_LOCK,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        done = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()["version"]
        for version, step in enumerate(migrations.MIGRATIONS[done:], start=done + 1):
            conn.execute(step)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (%s, %s)",
                (version, now()),
            )
    return len(migrations.MIGRATIONS)


def read(query):
    """Run a read a second time when its connection breaks under it.

    Neon can close a connection at any moment, for example when it scales to
    zero. A read changes nothing, so a second run is safe. Writes are never
    run twice, because a COMMIT can land even when its reply is lost. A full
    pool is not tried again either: that would only double the wait.
    """
    @functools.wraps(query)
    def read_again(*args, **kwargs):
        try:
            return query(*args, **kwargs)
        except PoolTimeout:
            raise
        except OperationalError:
            return query(*args, **kwargs)
    return read_again


# The reads that open pages repeat: the gate board every 30 seconds, the
# visitor's status, and the guard list on every gate call. They come from
# memory until a change to the data, so Neon can sleep while pages stay
# open. This holds because one process makes every write: keep --workers 1.
# The old version can still write while Render swaps versions, so nothing is
# kept in the first minutes after start.
CACHE_AFTER_SECONDS = 120
CACHE_LIMIT = 500
_cache: dict = {}
_cache_lock = threading.Lock()
_changes = [0]
_started = time.monotonic()


def forget_cache():
    """Drop every cached read. Each write calls this, and the timer does every round."""
    with _cache_lock:
        _changes[0] += 1
        _cache.clear()


def writes(change):
    """A change to the data. Once it ends, after its commit, the cached reads are stale."""
    @functools.wraps(change)
    def write_then_forget(*args, **kwargs):
        try:
            return change(*args, **kwargs)
        finally:
            forget_cache()
    return write_then_forget


def cached(query):
    """A read kept in memory until the next write. A None answer is never kept."""
    @functools.wraps(query)
    def from_memory(*args):
        key = (query.__name__, *args)
        with _cache_lock:
            hit = _cache.get(key)
            seen = _changes[0]
        if hit is None:
            hit = query(*args)
            with _cache_lock:
                # Kept only if no write ran during the query, or it may be stale.
                if (hit is not None and _changes[0] == seen
                        and time.monotonic() - _started > CACHE_AFTER_SECONDS):
                    if len(_cache) >= CACHE_LIMIT:
                        _cache.clear()
                    _cache[key] = hit
        # Each caller gets a copy, so a change to it never reaches the cache.
        return copy.deepcopy(hit)
    return from_memory


def ping():
    """True when the database answers. For the health check."""
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as failure:  # any failure means the check failed
        log.warning("Health check: the database did not answer: %s", failure)
        return False


def is_new_message(message_id):
    """False when this WhatsApp message was already handled."""
    if not message_id:
        return True
    with connect() as conn:
        added = conn.execute(
            "INSERT INTO seen_messages (id, seen) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (message_id, now()),
        ).rowcount
    return added == 1

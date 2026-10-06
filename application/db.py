"""The Postgres pool, the read cache and the stored values. Queries: visits, entries, people."""

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
# Declined because the number went on the blacklist while the request was open.
BY_BLACKLIST = "blacklist"
# Decided on the admin page by a super admin. decided_phone then holds that admin's label.
BY_ADMIN = "admin"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


# The open pool, or none yet. A list, so its type is never None.
_pools: list[ConnectionPool] = []
_pool_lock = threading.Lock()
_closed = False


def connect() -> AbstractContextManager[Any]:
    """A pooled connection that commits at the end. The pool opens on first use, never at import."""
    with _pool_lock:
        if _closed:
            raise RuntimeError("The database is closed: the app is shutting down")
        if not _pools:
            _pools.append(ConnectionPool(
                config.DATABASE_URL,
                # Four gunicorn threads plus the timer.
                min_size=2,
                max_size=5,
                # A request waits at most 5 s for a connection.
                timeout=5,
                # A hung connect fails after 10 s. Keepalives find a dead connection in a minute.
                kwargs={
                    "row_factory": dict_row,
                    # Neon's pooled connection cannot keep prepared statements.
                    "prepare_threshold": None,
                    "connect_timeout": 10,
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 3,
                },
                # Neon closes idle connections when it scales to zero.
                check=ConnectionPool.check_connection,
                open=True,
            ))
    return _pools[0].connection()


def close():
    """Close the pool before exit. Python 3.14 cannot close it at shutdown. Safe to call twice."""
    global _closed
    with _pool_lock:
        _closed = True
        closing = _pools[:]
        _pools.clear()
    for pool in closing:
        pool.close(timeout=5)


# Scripts and tests close the pool on exit too. The app stops its timer first.
atexit.register(close)

log = logging.getLogger(__name__)

# Waits between start tries while Neon wakes. A worker that fails to start stops gunicorn.
START_WAITS = (1, 2, 4, 8)


def init():
    """Run the new migrations, trying again while the database wakes. Returns the version."""
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
    """Run a read again if its connection drops. Never a write: its COMMIT may have landed."""
    @functools.wraps(query)
    def read_again(*args, **kwargs):
        try:
            return query(*args, **kwargs)
        except PoolTimeout:
            raise
        except OperationalError:
            return query(*args, **kwargs)
    return read_again


# Page reads come from memory until the next write, so Neon can sleep. This needs one
# writing process (--workers 1), and is off in the first minutes while Render swaps versions.
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


def cached(query=None, *, shared=False):
    """A read kept in memory until the next write. A None answer is never kept.

    Each caller gets a copy, which costs O(n) for n rows. With shared=True the read returns
    something no caller can change, such as a frozenset or a MappingProxyType, so every
    caller gets the same object, and a lookup in it costs O(1)."""
    if query is None:
        return functools.partial(cached, shared=shared)

    @functools.wraps(query)
    def from_memory(*args):
        # The module too: staff.everyone and blacklist.everyone are different reads.
        key = (query.__module__, query.__name__, *args)
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
        return hit if shared else copy.deepcopy(hit)
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

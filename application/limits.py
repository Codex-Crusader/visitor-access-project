"""How often one caller may use the public addresses."""

import threading
import time
from collections import deque

from flask import request

import config

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

    On Render, Cloudflare sits in front of Render's own proxies. Cloudflare
    puts the visitor's address in True-Client-IP and replaces a value the
    visitor sent. The last X-Forwarded-For entry is one of Render's internal
    proxies, which changes from call to call, so it counted proxies, not
    visitors. Without True-Client-IP, that last entry is still the safest:
    the first one is whatever the visitor chose to send.
    """
    if config.BEHIND_PROXY:
        visitor = request.headers.get("True-Client-IP", "").strip()
        if visitor:
            return visitor
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
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


def too_many(bucket, limit, seconds, who=None):
    """True when the caller (or who, when given) is over the limit. Counts every allowed call.

    The check and the count happen under one lock. Two threads can therefore
    never both see room for one more call and both take it.
    """
    key = (bucket, caller() if who is None else who)
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

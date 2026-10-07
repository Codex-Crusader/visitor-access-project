"""How often one caller may use the public addresses."""

import threading
import time
from collections import deque

from flask import request

import config

# (bucket, caller) -> times of allowed calls, oldest first. O(1) per call on average.
_hits = {}
_hits_lock = threading.Lock()
_last_sweep = [0.0]
SWEEP_SECONDS = 60
MAX_CALLERS = 10000
# Past this, the quietest callers are forgotten at once, so many addresses cannot fill memory.
HARD_MAX_CALLERS = 50000
KEEP_SECONDS = 3600  # the longest window any limit uses


def caller():
    """The visitor's address. Behind Render, True-Client-IP from Cloudflare: the last
    X-Forwarded-For entry is a Render proxy that changes per call, and the first can be forged."""
    if config.BEHIND_PROXY:
        visitor = request.headers.get("True-Client-IP", "").strip()
        if visitor:
            return visitor
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.remote_addr or "?"


def _sweep(moment):
    """Drop callers silent for the longest window. At most once a minute, and only when big.

    Past HARD_MAX_CALLERS it runs at once, and forgets the quietest callers down to
    MAX_CALLERS: O(n log n), but only after n new callers."""
    full = len(_hits) > HARD_MAX_CALLERS
    if not full and (len(_hits) <= MAX_CALLERS or moment - _last_sweep[0] < SWEEP_SECONDS):
        return
    _last_sweep[0] = moment
    old = moment - KEEP_SECONDS
    for stale in [key for key, times in _hits.items() if not times or times[-1] <= old]:
        del _hits[stale]
    if len(_hits) > HARD_MAX_CALLERS:
        by_last_call = sorted(_hits, key=lambda key: _hits[key][-1] if _hits[key] else 0.0)
        for quiet in by_last_call[:len(_hits) - MAX_CALLERS]:
            del _hits[quiet]


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
    """True when the caller, or who, is over the limit. One lock: two threads never both pass."""
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

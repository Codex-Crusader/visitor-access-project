"""Campus visitor access: makes the Flask app, adds the response rules, runs the timer."""

import atexit
import threading
import time

from flask import Flask, jsonify, request

import config
import db
import limits
import pages
import timer
import whatsapp
from routes import admin, gate, visitor, webhook

app = Flask(__name__, static_folder=str(pages.STATIC), static_url_path="")
# The largest call is an entry with its photo, as base64. Anything bigger gets 413.
app.config["MAX_CONTENT_LENGTH"] = 1_000_000
if config.ADMIN_LOCKED:
    app.logger.warning(config.ADMIN_LOCKED)

for part in (pages, visitor, gate, admin, webhook):
    app.register_blueprint(part.bp)

# Meta is asked whether the token works at most this often. A failure is asked again sooner.
META_CHECK_SECONDS = 3600
META_RETRY_SECONDS = 300


@app.errorhandler(413)
def too_big(_error):
    return jsonify(error="That is too big. Take the photo again."), 413


@app.after_request
def add_security_headers(response):
    for name, value in pages.SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.after_request
def keep_versioned_scripts(response):
    """A script asked for by its current hash is kept for a year."""
    version = request.args.get("v")
    if (response.status_code == 200 and version
            and version == pages.SCRIPT_VERSIONS.get(request.path.lstrip("/"))):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


_meta_check = {"at": 0.0, "ok": False}
_meta_lock = threading.Lock()


def forget_meta_check():
    """Make the next health check ask Meta again. The tests call this."""
    with _meta_lock:
        _meta_check.update(at=0.0, ok=False)


def whatsapp_ok():
    """True when Meta accepts the token. Asked at most hourly: the health address is public."""
    with _meta_lock:
        age = time.time() - _meta_check["at"]
        if age < (META_CHECK_SECONDS if _meta_check["ok"] else META_RETRY_SECONDS):
            return _meta_check["ok"]
        ok = whatsapp.token_works()
        _meta_check.update(at=time.time(), ok=ok)
        return ok


@app.get("/api/health")
def health():
    """200 when the database and Meta work, else 503. Says which part failed, never why."""
    if limits.too_many("health", 30, 60):
        return jsonify(error="Too many checks. Try again in a minute."), 429
    checks = {"database": db.ping(), "whatsapp": whatsapp_ok()}
    return jsonify(checks), 200 if all(checks.values()) else 503


def start_background():
    """Build the tables and start the timer, in the serving process. See gunicorn.conf.py."""
    db.init()
    timer.background.start()
    atexit.register(stop_background)


def stop_background():
    """Stop the timer after its round, then close the database. Safe to call twice."""
    timer.stopping.set()
    timer.wake.set()
    if timer.background.is_alive():
        timer.background.join(timeout=10)
    db.close()


if __name__ == "__main__":
    start_background()
    app.run(host="0.0.0.0", port=5000)

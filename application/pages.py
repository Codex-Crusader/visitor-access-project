"""The three pages, their script versions, and the security headers."""

import hashlib
import re
from pathlib import Path

from flask import Blueprint, Response, request

bp = Blueprint("pages", __name__)


STATIC = Path(__file__).parent / "static"


def short_hash(data: bytes):
    return hashlib.sha256(data).hexdigest()[:10]


# Scripts load as app.js?v=<hash>, kept for a year. The pages are checked on every load.
SCRIPT_VERSIONS = {path.name: short_hash(path.read_bytes()) for path in STATIC.glob("*.js")}
SCRIPT_TAG = re.compile(r'<script src="([\w.-]+\.js)"></script>')


def with_versions(html):
    return SCRIPT_TAG.sub(
        lambda tag: f'<script src="{tag[1]}?v={SCRIPT_VERSIONS[tag[1]]}"></script>', html
    )


PAGES = {
    name: with_versions((STATIC / name).read_text(encoding="utf-8"))
    for name in ("index.html", "gate.html", "admin.html")
}
PAGE_TAGS = {name: short_hash(html.encode()) for name, html in PAGES.items()}


def page(name):
    response = Response(PAGES[name], mimetype="text/html")
    response.headers["Cache-Control"] = "no-cache"
    response.set_etag(PAGE_TAGS[name])
    return response.make_conditional(request)


# Inline onclick and styles need 'unsafe-inline'. Nothing loads from another site.
CONTENT_POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';"
    " img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none';"
    " form-action 'self'; frame-ancestors 'self'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_POLICY,
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    # The visitor's private link is in the address, so no page passes it on.
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


@bp.get("/")
def index():
    return page("index.html")


@bp.get("/gate")
def gate():
    return page("gate.html")


@bp.get("/admin")
def admin():
    return page("admin.html")

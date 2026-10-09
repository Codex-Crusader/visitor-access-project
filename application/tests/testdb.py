"""A throwaway Postgres for the tests, or TEST_DATABASE_URL. Never point that at live data."""

import os
import tempfile

_server = None


def url():
    global _server
    given = os.getenv("TEST_DATABASE_URL", "").strip()
    if given:
        return given
    import pgserver

    _server = pgserver.get_server(tempfile.mkdtemp(), cleanup_mode="delete")
    return _server.get_uri()

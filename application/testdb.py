"""A throwaway Postgres for the tests.

The tests import this before config, and pass url() as DATABASE_URL. Each
run starts its own empty Postgres in a temporary folder, from the pgserver
package, and stops it at exit. Nothing touches the live database.

To test against another Postgres, set TEST_DATABASE_URL. The tests write to
it and delete rows, so never point it at the live database.
"""

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

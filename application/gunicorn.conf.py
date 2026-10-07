"""Gunicorn settings. Render uses --preload, so the worker opens the database and starts the
timer after the fork: a connection or thread made in the master breaks in the worker."""

# noinspection PyPackageRequirements
from gunicorn.glogging import Logger


class RedactingLogger(Logger):
    """Gunicorn's access log, with redact() on the request line and the path."""

    def atoms(self, resp, req, environ, request_time):
        # Here, not at the top: gunicorn reads this file before the app folder is importable.
        from redaction import redact

        found = super().atoms(resp, req, environ, request_time)
        hidden = {name: redact(value) for name, value in found.items()
                  if name in ("r", "U", "f") and isinstance(value, str)}
        return {**found, **hidden}


logger_class = RedactingLogger


def post_worker_init(_worker):
    import app

    app.start_background()


# Close the pool here, before shutdown: Python 3.14 cannot close it later.
def worker_exit(_server, _worker):
    import app

    app.stop_background()

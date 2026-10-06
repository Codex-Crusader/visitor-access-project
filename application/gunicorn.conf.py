"""Gunicorn settings. Render uses --preload, so the worker opens the database and starts the
timer after the fork: a connection or thread made in the master breaks in the worker."""


def post_worker_init(_worker):
    import app

    app.start_background()


# Close the pool here, before shutdown: Python 3.14 cannot close it later.
def worker_exit(_server, _worker):
    import app

    app.stop_background()

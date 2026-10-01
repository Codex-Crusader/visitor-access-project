"""Gunicorn settings. Gunicorn reads this file from the folder it starts in.

Render runs gunicorn with --preload, so the master process imports app.py
and then forks the worker that serves requests. A database connection made
at import would live in the master. The worker would share its encrypted
socket, which corrupts it, and would get none of the pool's threads, because
threads do not survive a fork. So the worker opens the database and starts
the escalation timer itself, here, after the fork.
"""


def post_worker_init(_worker):
    import app

    app.start_background()


# Runs in the worker as it exits, before Python starts shutting down. Closing
# the pool later, during shutdown, fails on Python 3.14: it cannot join the
# pool's threads then, and the connections are dropped instead of closed.
def worker_exit(_server, _worker):
    import app

    app.stop_background()

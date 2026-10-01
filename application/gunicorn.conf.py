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

"""Secrets in request paths, hidden from log lines."""

import re

# A visitor's link and the pass and staff codes open things, so log lines hide them.
SECRET_PATH = re.compile(r"(/api/(?:visit|pass|staff)/)[^/?\s\"]+")


def one_line(value):
    """A value for a log line on one line, so a line break in it cannot forge a second line."""
    return str(value).replace("\r", " ").replace("\n", " ")


def redact(text):
    """The text with each secret in a path replaced by <hidden>."""
    return SECRET_PATH.sub(r"\1<hidden>", text)

"""Tags: one sub-division for each office and each allow list person, so long lists stay
easy to read. Each list has its own tags. An empty tag means no tag."""

import checks
import db

TAG_LENGTH = 40
# Each list with a tag, and the column that names one row in it. Fixed names, so safe in SQL.
LISTS = {"offices": "name", "staff": "code"}


@db.read
def existing(table):
    """The tags in use in one list, in A to Z order."""
    assert table in LISTS
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT tag FROM {table} WHERE tag <> '' ORDER BY tag"
        ).fetchall()
    return [row["tag"] for row in rows]


def clean(table, raw):
    """(tag, problem). A tag that matches one in use, in any case, takes its spelling."""
    raw = str(raw or "")
    tag = checks.clean_text(raw) if len(raw) <= TAG_LENGTH else None
    if tag is None:
        return None, f"Write the tag in one line, {TAG_LENGTH} letters at most."
    same = [old for old in existing(table) if old.lower() == tag.lower()]
    return (same[0] if same else tag), None


@db.writes
def set_tag(table, key, tag):
    """Give one row a tag. False when no row has that key."""
    assert table in LISTS
    with db.connect() as conn:
        return conn.execute(
            f"UPDATE {table} SET tag = %s WHERE {LISTS[table]} = %s", (tag, key)
        ).rowcount == 1


@db.writes
def rename(table, old, new):
    """Give every row with tag old the tag new. Returns how many rows changed."""
    assert table in LISTS
    with db.connect() as conn:
        return conn.execute(
            f"UPDATE {table} SET tag = %s WHERE tag = %s", (new, old)
        ).rowcount

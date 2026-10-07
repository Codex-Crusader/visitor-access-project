"""Entries and exits at the gate, and the visitor's photo."""

import blacklist
import db
import visits

# Inside the UPDATE, so a number blacklisted a moment ago never gets in.
NOT_BLACKLISTED = blacklist.not_listed("visits.phone")


@db.writes
def check_in(reference, by, image):
    """Let an approved visitor in and save the photo. The UPDATE decides, so one guard wins."""
    stamp = db.now()
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE visits SET status = %s, entered_at = %s, entered_by = %s WHERE reference = %s"
            " AND status = %s AND created_at >= %s" + NOT_BLACKLISTED + " RETURNING *",
            (db.INSIDE, stamp, by, reference, db.APPROVED, visits.pass_cutoff()),
        ).fetchone()
        if row is not None:
            conn.execute(
                "INSERT INTO photos (reference, image, taken_at) VALUES (%s, %s, %s)"
                " ON CONFLICT (reference) DO UPDATE SET image = EXCLUDED.image,"
                " media_id = NULL, taken_at = EXCLUDED.taken_at",
                (reference, image, stamp),
            )
    return visits.to_dict(row) if row is not None else None


@db.writes
def check_out(reference, by):
    """Close the pass on the way out. Returns the visit, or None unless the visitor is inside."""
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE visits SET status = %s, exited_at = %s, exited_by = %s WHERE reference = %s"
            " AND status = %s RETURNING *",
            (db.CLOSED, db.now(), by, reference, db.INSIDE),
        ).fetchone()
    return visits.to_dict(row) if row is not None else None


def wait_for_photo(guard, reference, minutes):
    """Remember that this guard owes a photo for this pass. Returns None, or the reference of an
    earlier pass that still waits for its photo: a photo must never go to the wrong visitor.

    One statement decides. An earlier wait gives way only when it is for the same pass, when it
    is older than minutes, or when that pass can no longer enter."""
    with db.connect() as conn:
        taken = conn.execute(
            "INSERT INTO photo_waits (guard, reference, asked) VALUES (%s, %s, %s)"
            " ON CONFLICT (guard) DO UPDATE SET reference = EXCLUDED.reference,"
            " asked = EXCLUDED.asked"
            " WHERE photo_waits.reference = EXCLUDED.reference OR photo_waits.asked < %s"
            " OR NOT EXISTS (SELECT 1 FROM visits WHERE visits.reference = photo_waits.reference"
            " AND visits.status = %s)"
            " RETURNING reference",
            (guard, reference, db.now(), db.ago(minutes / 1440), db.APPROVED),
        ).fetchone()
        if taken is not None:
            return None
        pending = conn.execute(
            "SELECT reference FROM photo_waits WHERE guard = %s", (guard,)
        ).fetchone()
    return pending["reference"] if pending else None


def cancel_photo(guard):
    """Drop the photo this guard owes. Returns that pass's reference, or None."""
    with db.connect() as conn:
        dropped = conn.execute(
            "DELETE FROM photo_waits WHERE guard = %s RETURNING reference", (guard,)
        ).fetchone()
    return dropped["reference"] if dropped else None


@db.writes
def enter_with_photo(guard, minutes, media_id, by):
    """Let in the visitor this guard's photo is for. Returns (reference, entered).

    One statement reads and ends the wait, so one IN never lets in two people."""
    with db.connect() as conn:
        wait = conn.execute(
            "DELETE FROM photo_waits WHERE guard = %s RETURNING reference, asked", (guard,)
        ).fetchone()
        if wait is None or wait["asked"] < db.ago(minutes / 1440):
            return None, False

        reference, stamp = wait["reference"], db.now()
        changed = conn.execute(
            "UPDATE visits SET status = %s, entered_at = %s, entered_by = %s WHERE reference = %s"
            " AND status = %s AND created_at >= %s" + NOT_BLACKLISTED,
            (db.INSIDE, stamp, by, reference, db.APPROVED, visits.pass_cutoff()),
        ).rowcount
        if changed == 1:
            conn.execute(
                "INSERT INTO photos (reference, media_id, taken_at) VALUES (%s, %s, %s)"
                " ON CONFLICT (reference) DO UPDATE"
                " SET media_id = EXCLUDED.media_id, taken_at = EXCLUDED.taken_at",
                (reference, media_id, stamp),
            )
    return reference, changed == 1


PHOTO_BATCH = 50


def stored_photos():
    """(reference, JPEG bytes) for every gate page photo, 50 per database trip, for the ZIP."""
    after = ""
    while True:
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT reference, image FROM photos WHERE image IS NOT NULL AND reference > %s"
                " ORDER BY reference LIMIT %s",
                (after, PHOTO_BATCH),
            ).fetchall()
        for row in rows:
            yield row["reference"], bytes(row["image"])
        if len(rows) < PHOTO_BATCH:
            return
        after = rows[-1]["reference"]


@db.read
def photo_of(reference):
    """The stored photo record for a pass, or None. image is None for a WhatsApp photo."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT media_id, image, taken_at FROM photos WHERE reference = %s", (reference,)
        ).fetchone()
    if not row:
        return None
    photo = dict(row)
    photo["image"] = bytes(photo["image"]) if photo["image"] is not None else None
    return photo

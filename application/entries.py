"""Entries and exits at the gate, and the visitor's photo."""

import db
import visits
from db import APPROVED, CLOSED, INSIDE


@db.writes
def check_in(reference, by, image):
    """Let an approved, unexpired visitor in and save the photo. Returns the visit, or None.

    The checks sit in the UPDATE, so of two guards one wins and only that photo is saved.
    """
    stamp = db.now()
    with db.connect() as conn:
        row = conn.execute(
            "UPDATE visits SET status = %s, entered_at = %s, entered_by = %s WHERE reference = %s"
            " AND status = %s AND created_at >= %s RETURNING *",
            (INSIDE, stamp, by, reference, APPROVED, visits.pass_cutoff()),
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
            (CLOSED, db.now(), by, reference, INSIDE),
        ).fetchone()
    return visits.to_dict(row) if row is not None else None


def wait_for_photo(guard, reference):
    """Remember that this guard owes a photo for this pass. Replaces any earlier one."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO photo_waits (guard, reference, asked) VALUES (%s, %s, %s)"
            " ON CONFLICT (guard) DO UPDATE"
            " SET reference = EXCLUDED.reference, asked = EXCLUDED.asked",
            (guard, reference, db.now()),
        )


@db.writes
def enter_with_photo(guard, minutes, media_id, by):
    """Let in the visitor this guard's photo is for. Returns (reference, entered).

    reference is None when no IN from this guard is waiting, or when the IN is
    older than `minutes`. entered is False unless the pass was approved.

    Every photo ends the wait, so a second photo can never let a second person
    in on the same IN. Everything happens in one transaction: if any step
    fails, the wait is still there and the guard can send the photo again.
    The wait is read and deleted in one statement, so of two photos sent at
    the same moment, only one gets it.
    """
    with db.connect() as conn:
        wait = conn.execute(
            "DELETE FROM photo_waits WHERE guard = %s RETURNING reference, asked", (guard,)
        ).fetchone()
        if wait is None or wait["asked"] < db.ago(minutes / 1440):
            return None, False

        reference, stamp = wait["reference"], db.now()
        changed = conn.execute(
            "UPDATE visits SET status = %s, entered_at = %s, entered_by = %s WHERE reference = %s"
            " AND status = %s AND created_at >= %s",
            (INSIDE, stamp, by, reference, APPROVED, visits.pass_cutoff()),
        ).rowcount
        if changed == 1:
            conn.execute(
                "INSERT INTO photos (reference, media_id, taken_at) VALUES (%s, %s, %s)"
                " ON CONFLICT (reference) DO UPDATE"
                " SET media_id = EXCLUDED.media_id, taken_at = EXCLUDED.taken_at",
                (reference, media_id, stamp),
            )
    return reference, changed == 1


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

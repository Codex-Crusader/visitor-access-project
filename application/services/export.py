"""The admin's downloads: the visit log as a ZIP with the photos and a page that shows each
visit beside its photo, and the staff entry log as its own CSV. The ZIP streams, so thousands of
photos never sit in memory at once. Times are campus time, and every column has a plain heading."""

import csv
import html
import io
import re
import time
import zipfile
from datetime import datetime, timezone
from typing import Any

from core import config, db
from models import audit, blacklist, entries, staff, visits

ZONE = config.WORK_TIMEZONE.key


def local(stamp, shape="%Y-%m-%d %H:%M"):
    """A stored UTC time as campus time, as 2026-10-06 16:05. A spreadsheet reads it as a date."""
    if not stamp:
        return ""
    moment: datetime = datetime.fromisoformat(stamp)
    return moment.astimezone(config.WORK_TIMEZONE).strftime(shape)


STATUS_WORDS = {
    "pending": "Waiting", "escalated": "Asked again", "approved": "Approved",
    "declined": "Declined", "inside": "Inside", "closed": "Left", "expired": "Expired",
}
DECIDED_BY = {
    "main": "Approver {who}", "backup": "Backup approver {who}",
    "auto": "Approved by itself: no answer in time", "admin": "{who} on the admin page",
    "blacklist": "The blacklist",
}


def decided_by(visit):
    words = DECIDED_BY.get(visit.get("decided_by") or "", "")
    return " ".join(words.format(who=visit.get("decided_phone") or "").split())


def photo_file(reference):
    return f"photos/{reference}.jpg"


# Each column as (heading, how to read it from a row). A name reads that field as it is.
VISIT_COLUMNS = (
    ("Reference", "reference"), ("Name", "name"), ("Phone", "phone"), ("Address", "address"),
    ("Reason", "reason"), ("Office", "office"), ("Visiting", "visiting"),
    ("People with them", lambda v: ", ".join(v["guests"])),
    ("Status", lambda v: STATUS_WORDS.get(v["status"], v["status"])),
    (f"Requested ({ZONE})", lambda v: local(v["created_at"])),
    (f"Asked again ({ZONE})", lambda v: local(v["escalated_at"])),
    (f"Decided ({ZONE})", lambda v: local(v["decided_at"])),
    ("Decided by", decided_by),
    (f"Entered ({ZONE})", lambda v: local(v["entered_at"])),
    ("Entered by", "entered_by"),
    (f"Exited ({ZONE})", lambda v: local(v["exited_at"])),
    ("Exited by", "exited_by"),
    (f"Photo taken ({ZONE})", lambda v: local(v["photo_at"])),
)
# In the ZIP only. Empty for a photo sent on WhatsApp, which stays in the guard's chat.
ZIP_VISIT_COLUMNS = (
    *VISIT_COLUMNS,
    ("Photo file", lambda v: photo_file(v["reference"]) if v["photo_stored"] else ""),
)
# A staff visit with one side missing, see staff.pair_visits().
NO_EXIT = "EXIT NOT RECORDED"
NO_ENTRY = "ENTRY NOT RECORDED"
STILL_INSIDE = "Still inside"


def exit_cell(row):
    if row["out"]:
        return local(row["out"], "%H:%M")
    still = row.get("open") and row["in"] >= db.ago(staff.SHIFT_HOURS / 24)
    return STILL_INSIDE if still else NO_EXIT


# One row per staff visit. The date in its own column, so a spreadsheet filter shows one day.
ALLOW_COLUMNS = (
    (f"Date ({ZONE})", lambda r: local(r["in"] or r["out"], "%Y-%m-%d")), ("Name", "name"),
    ("Allow list code", "code"), ("WhatsApp number", "phone"),
    (f"Entry time ({ZONE})", lambda r: local(r["in"], "%H:%M") if r["in"] else NO_ENTRY),
    ("Entered by", "in_by"),
    (f"Exit time ({ZONE})", exit_cell), ("Exited by", "out_by"),
)
BLOCKED_COLUMNS = (
    (f"When ({ZONE})", lambda a: local(a["at"])), ("Name", "name"), ("Phone", "phone"),
    ("What happened", "what"), ("Detail", "detail"), ("Where", "by_whom"),
)
CHANGE_COLUMNS = (
    (f"When ({ZONE})", lambda c: local(c["at"])), ("Who", "by_whom"), ("What", "action"),
    ("Details", "detail"),
)

# Spreadsheets run a cell starting with these as a formula. A leading quote stops that.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
# A checked number, as +919876543210. Written as ="+91…", so a spreadsheet shows it as text:
# not as 9.19E+11, and not with a stray quote. Only + and digits, so nothing can run.
PHONE = re.compile(r"^\+\d{6,15}$")


def safe_cell(value):
    text = "" if value is None else str(value)
    if PHONE.match(text):
        return f'="{text}"'
    return "'" + text if text.startswith(FORMULA_START) else text


def read(row, how) -> Any:
    return how(row) if callable(how) else row.get(how)


PIECE_ROWS = 500


def csv_pieces(columns, rows):
    """A CSV that Excel opens with every letter right: it starts with the UTF-8 mark.

    In pieces of 500 rows, so a download streams and never holds the whole file."""
    buffer = io.StringIO()
    buffer.write("﻿")
    writer = csv.writer(buffer)
    writer.writerow([heading for heading, _ in columns])
    for number, row in enumerate(rows, 1):
        writer.writerow([safe_cell(read(row, how)) for _, how in columns])
        if number % PIECE_ROWS == 0:
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate()
    yield buffer.getvalue()


def staff_entries_csv():
    """Every staff visit still kept, oldest first, one row each, in pieces."""
    return csv_pieces(ALLOW_COLUMNS, staff.all_visits())


def visit_rows(newest_first=False):
    """Every visit, oldest first, read in batches."""
    return visits.all_visits(newest_first)


def file_name(name, extension):
    """The name with the campus date, the same date as the rows. Not UTC: at 02:00 in India it is
    still yesterday in UTC."""
    stamp = datetime.now(config.WORK_TIMEZONE).strftime("%Y-%m-%d")
    return f"{name}-{stamp}.{extension}"


README = """The visit log from the campus visitor access app, downloaded {stamp} ({zone}).

visits.html            Open it in a browser: each visit with its gate photo.
visits.csv             Every visit, one row each. "Photo file" names its photo.
blocked-attempts.csv   Each time the blacklist stopped someone.
admin-changes.csv      Who changed what on the admin page, or by KEY.
photos/                The photos taken on the gate page, named by reference.

The staff entry log is a separate file: staff-entries-<date>.csv. It has one
row for each allow list visit, with its entry, its exit and the guards who
recorded them. Download log saves both files.

Times are campus time, {zone}. A photo sent on WhatsApp is not here: it stays
in the guard's WhatsApp chat. This copy holds personal details and faces.
Keep it on a locked device, and delete it when the campus rules say so.
"""

PAGE_STYLE = """
body{margin:0;padding:24px;background:#F5F8FB;color:#0F1822;
 font:15px/1.45 -apple-system,"Segoe UI",Roboto,Arial,sans-serif}
h1{margin:0 0 4px;font-size:1.4rem}p.sub{margin:0 0 20px;color:#5A6979}
.visit{display:flex;gap:16px;background:#fff;border:1px solid #E2E8EE;border-radius:14px;
 padding:14px;margin:0 0 12px;break-inside:avoid}
.photo{flex:none;width:150px;height:150px;border-radius:10px;background:#EDF2F9;object-fit:cover;
 display:flex;align-items:center;justify-content:center;text-align:center;color:#5A6979;
 font-size:.8rem;padding:8px;box-sizing:border-box}
img.photo{padding:0}
dl{display:grid;grid-template-columns:max-content 1fr;gap:3px 14px;margin:0;font-size:.9rem}
dt{color:#5A6979}dd{margin:0;font-weight:600;overflow-wrap:anywhere}
h2{margin:0 0 6px;font-size:1.05rem}
@media(max-width:560px){.visit{flex-direction:column}}
"""


def visit_card(visit):
    """One visit on the page, beside its photo. Every value is escaped."""
    values = {heading: str(read(visit, how) or "") for heading, how in VISIT_COLUMNS}
    if visit["photo_stored"]:
        picture = (f'<img class="photo" loading="lazy" src="{photo_file(visit["reference"])}"'
                   f' alt="{html.escape(visit["name"])} at the gate">')
    else:
        why = "Photo in the guard's WhatsApp chat" if visit["photo_at"] else "No photo"
        picture = f'<div class="photo">{why}</div>'
    shown = "".join(f"<dt>{html.escape(k)}</dt><dd>{html.escape(v)}</dd>"
                    for k, v in values.items() if v and k not in ("Reference", "Name"))
    return (f'<div class="visit">{picture}<div><h2>{html.escape(visit["name"])}'
            f' · {html.escape(visit["reference"])}</h2><dl>{shown}</dl></div></div>')


def visits_page(rows, count, stamp):
    """One page with every visit and its photo, newest first, in pieces of 500 visits. rows
    come newest first."""
    yield (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f"<title>Visit log</title><style>{PAGE_STYLE}</style></head><body>"
           f"<h1>Visit log</h1><p class=\"sub\">{count} visits, newest first. Downloaded"
           f" {html.escape(stamp)}. Times are {html.escape(ZONE)} time.</p>")
    cards = []
    for visit in rows:
        cards.append(visit_card(visit))
        if len(cards) == PIECE_ROWS:
            yield "".join(cards)
            cards.clear()
    yield "".join(cards) + "</body></html>"


class _Chunks:
    """A write-only file that hands its bytes on. ZipFile writes to it without seeking."""

    def __init__(self):
        self.parts = []

    def write(self, data):
        self.parts.append(bytes(data))
        return len(data)

    def flush(self):
        pass

    def take(self):
        data = b"".join(self.parts)
        self.parts.clear()
        return data


def zip_parts():
    """The ZIP, piece by piece: the notes, the page, the CSV files, then one photo at a time.
    The visits are read in batches, so the memory it needs does not grow with the log.

    The text files are compressed, often to a tenth. Photos are already JPEG, so they are
    stored as they are."""
    # The compressor holds some text back, so a piece can be empty. Only data goes out.
    return (part for part in _zip_bytes() if part)


def _zip_bytes():
    stamp = local(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    sink = _Chunks()
    texts = (
        ("README.txt", [README.format(stamp=stamp, zone=ZONE)]),
        ("visits.html", visits_page(visit_rows(newest_first=True), visits.count(), stamp)),
        ("visits.csv", csv_pieces(ZIP_VISIT_COLUMNS, visit_rows())),
        ("blocked-attempts.csv", csv_pieces(BLOCKED_COLUMNS, blacklist.all_attempts())),
        ("admin-changes.csv", csv_pieces(CHANGE_COLUMNS, audit.everything())),
    )
    # ZipFile only writes to the sink, so the writable part of a file is enough.
    # noinspection PyTypeChecker
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED) as archive:
        for name, pieces in texts:
            with archive.open(text_entry(name), "w") as file:
                for piece in pieces:
                    file.write(piece.encode())
                    yield sink.take()
        for reference, image in entries.stored_photos():
            archive.writestr(photo_file(reference), image)
            yield sink.take()
    yield sink.take()


def text_entry(name):
    """A compressed text file in the ZIP, dated now, as writestr() dates one."""
    info = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info

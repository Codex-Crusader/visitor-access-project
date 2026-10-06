"""Checks on what visitors and guards send: the form fields, phone numbers, photos."""

import base64
import binascii
import io
import re
import unicodedata

from PIL import Image

FIELDS = ("name", "phone", "address", "reason", "visiting")

# The gate page shrinks its photo to about 30-40 KB. The server takes up to this.
PHOTO_BYTES = 150_000
# The longest side a photo may claim. The page sends 640 pixels. The limit is
# read from the file's header, before the picture is decoded.
PHOTO_SIDE = 2000
Image.MAX_IMAGE_PIXELS = PHOTO_SIDE * PHOTO_SIDE
PHOTO_QUALITY = 60
PHOTO_PREFIX = "data:image/jpeg;base64,"
NO_PHOTO = ("Take a photo of the visitor first. The entry needs one."
            " If this page shows no photo button, reload the page.")

# Every field is one line of plain text. These characters are not text:
# line breaks, terminal control codes, invisible marks, and the overrides
# that make written text run the other way. Unicode files them under
# C (other) and Z (separator). A visitor who puts them in a name is not
# writing a name. They are trying to forge extra lines in the approval
# message the approver reads on WhatsApp.
NOT_TEXT = ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp")
MAX_LENGTH = 200


def clean_text(value):
    """One line of plain text, or None when the value is not plain text."""
    if any(unicodedata.category(letter) in NOT_TEXT for letter in value):
        return None
    return " ".join(value.split())


def clean_fields(payload):
    """Return (fields, guests, error)."""
    fields = {}
    for key in FIELDS:
        raw = str(payload.get(key, ""))
        if len(raw) > MAX_LENGTH:
            return None, None, f"{key} is too long"
        value = clean_text(raw)
        if value is None:
            return None, None, f"{key} has characters that are not allowed"
        if not value:
            return None, None, f"{key} is required"
        fields[key] = value

    digits = "".join(c for c in fields["phone"] if c.isdigit())
    if len(digits) != 10:
        return None, None, "phone must be 10 digits"

    raw_guests = payload.get("guests") or []
    if not isinstance(raw_guests, list):
        return None, None, "guests must be a list"
    guests = []
    for guest in raw_guests[:10]:
        name = clean_text(str(guest)[:MAX_LENGTH])
        if name is None:
            return None, None, "guests have characters that are not allowed"
        if name:
            guests.append(name)
    return fields, guests, None


PHONE = re.compile(r"^\+[1-9]\d{7,14}$")


def clean_phone(text):
    """+ and digits, as +911234567890, or None when it is not a phone number."""
    number = re.sub(r"[\s().-]", "", str(text or ""))
    return number if PHONE.match(number) else None


def read_photo(payload):
    """The photo in the call's JSON, redrawn as a clean JPEG, or None when it is not one.

    The server does not trust the page: it decodes the picture, and stores a
    new copy, so a broken file or a hidden location never reaches the database.
    """
    text = payload.get("photo") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.startswith(PHOTO_PREFIX):
        return None
    try:
        image = base64.b64decode(text[len(PHOTO_PREFIX):], validate=True)
    except (binascii.Error, ValueError):
        return None
    if not image.startswith(b"\xff\xd8\xff") or len(image) > PHOTO_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(image)) as picture:
            if picture.format != "JPEG" or max(picture.size) > PHOTO_SIDE:
                return None
            picture.load()
            clean = io.BytesIO()
            # Saved without its metadata, so no location or phone details stay.
            picture.convert("RGB").save(clean, "JPEG", quality=PHOTO_QUALITY)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    return clean.getvalue()

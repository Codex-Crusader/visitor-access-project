"""Checks the .env values and sends one test message. Run this before a demo."""

import sys
from typing import NoReturn


def fail(message) -> NoReturn:
    print(f"FAILED: {message}")
    sys.exit(1)


try:
    import config
except RuntimeError as missing:
    fail(f"{missing}. Open .env and fill that value in.")

# Imported after config, so a missing setting is reported above as a plain
# sentence rather than as a stack trace from inside this module.
import whatsapp  # noqa: E402

for name in ("MAIN_APPROVER", "BACKUP_APPROVER", "GATE_DESK_PHONE"):
    value = getattr(config, name)
    if not value.startswith("+"):
        fail(f"{name} is {value}. It must start with a plus and the country code.")
for reason, pair in config.APPROVERS.items():
    for value in pair:
        if not value.startswith("+"):
            fail(f"APPROVERS gives {value} for {reason}. It must start with a plus.")

print(f"Phone number ID {config.META_PHONE_NUMBER_ID}")
print(f"Approver        {config.MAIN_APPROVER}")
for reason, (main, backup) in config.APPROVERS.items():
    print(f"  {reason:<14} {main}, backup {backup}")
print(f"Signature check {'on' if config.META_APP_SECRET else 'off (META_APP_SECRET empty)'}")

# The app runs the migrations when it starts, so this runs them too, and a
# wrong DATABASE_URL shows up here rather than at the first visit.
import db  # noqa: E402

try:
    version = db.init()
except Exception as error:
    fail(f"Cannot use the database in DATABASE_URL. {error}")
print(f"Database        reachable, schema version {version}")
print()

# The real request goes out as the template, so the test does too. A plain
# text test would pass here and still never arrive after 24 quiet hours.
SAMPLE = {"reference": "VR-0000", "name": "Test Visitor", "phone": "0000000000",
          "address": "Test address", "reason": "Setup check", "visiting": "Nobody",
          "guests": []}

print(f"Sending a test message to {config.MAIN_APPROVER} ...")
try:
    if config.REQUEST_TEMPLATE:
        print(f"Using the template {config.REQUEST_TEMPLATE} ({config.TEMPLATE_LANGUAGE})")
        result = whatsapp.send_template(config.MAIN_APPROVER, whatsapp.template_values(SAMPLE))
    else:
        result = whatsapp.send(config.MAIN_APPROVER, "Test message from the visitor access app.")
except Exception as error:
    text = str(error)
    if "132001" in text:
        fail(
            f"Meta has no approved template named {config.REQUEST_TEMPLATE}.\n"
            "Check its status under WhatsApp Manager, then Message templates.\n"
            f"{error}"
        )
    if "190" in text or "OAuth" in text:
        fail(
            "Meta rejected the token. Temporary tokens last 24 hours.\n"
            "Generate a new one in the WhatsApp API Setup page and update META_TOKEN.\n"
            f"{error}"
        )
    if "131030" in text:
        fail(
            "That number is not on the test recipient list.\n"
            "Add it under Recipient in the WhatsApp API Setup page.\n"
            f"{error}"
        )
    fail(text)

print(f"Sent. Message id: {result['messages'][0]['id']}")
print("Check your phone.")

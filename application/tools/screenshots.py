"""Takes the README pictures of the app, with made-up visitors.

Run it from the app folder with: .venv\\Scripts\\python.exe tools\\screenshots.py [folder]
It saves six pictures in the folder, "pictures" if none is given. It uses a
throwaway Postgres and fake settings, and sends no WhatsApp message.
It needs Google Chrome and the playwright package, see docs/maintenance.md.
"""

import base64
import io
import json
import logging
import os
import sys
import threading
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# The app's modules are one folder up.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import testdb

os.environ.update(
    META_TOKEN="fake-token",
    META_PHONE_NUMBER_ID="100000000000000",
    META_VERIFY_TOKEN="fake-verify",
    META_APP_SECRET="",
    ALLOW_UNSIGNED_WEBHOOK="true",
    MAIN_APPROVER="+919000000001",
    BACKUP_APPROVER="+919000000002",
    GUARD="+919000000003",
    ADMIN_PHONE="+919000000004",
    GATE_KEY="demo-gate-key-long-enough",
    ADMIN_KEY="demo-admin-key-long-enough",
    GATE_DESK_PHONE="+912200000000",
    ESCALATE_MINUTES="15",
    APPROVERS="",
    DATABASE_URL=testdb.url(),
)

from PIL import Image
from werkzeug.serving import make_server

import app as application
import db
import visits
import whatsapp

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("playwright is not installed. Run:"
             " .venv\\Scripts\\python.exe -m pip install playwright==1.63.0")

PORT = 5055
BASE = f"http://127.0.0.1:{PORT}"
GATE_KEY, ADMIN_KEY = "demo-gate-key-long-enough", "demo-admin-key-long-enough"
APPROVER = "919000000001"
PHONE = {"viewport": {"width": 428, "height": 1000}, "device_scale_factor": 2,
         "is_mobile": True, "has_touch": True, "locale": "en-IN", "timezone_id": "Asia/Kolkata"}
DESKTOP = {"viewport": {"width": 1100, "height": 900}, "device_scale_factor": 2,
           "locale": "en-IN", "timezone_id": "Asia/Kolkata"}


def no_network(*_args, **_kwargs):
    return None


whatsapp.send = no_network
whatsapp.send_template = no_network
whatsapp._post = no_network
client = application.app.test_client()
message_ids = iter(range(1, 1000))


def say(sender, text):
    """A WhatsApp message from sender, as Meta posts it."""
    body = {"entry": [{"changes": [{"value": {"messages": [
        {"id": f"wamid.{next(message_ids)}", "from": sender, "type": "text",
         "text": {"body": text}}]}}]}]}
    client.post("/webhook/whatsapp", json=body)


def grey_photo():
    out = io.BytesIO()
    Image.new("RGB", (480, 360), (150, 160, 175)).save(out, "JPEG")
    return {"photo": application.PHOTO_PREFIX + base64.b64encode(out.getvalue()).decode()}


def move_back(reference, minutes):
    """Moves a visit's times back, so the lists read like a real morning."""
    columns = ("created_at", "escalated_at", "decided_at", "entered_at", "exited_at")
    with db.connect() as conn:
        row = conn.execute(f"SELECT {', '.join(columns)} FROM visits WHERE reference = %s",
                           (reference,)).fetchone()
        moved = [(datetime.fromisoformat(row[c]) - timedelta(minutes=minutes)).isoformat()
                 if row[c] else None for c in columns]
        conn.execute(f"UPDATE visits SET {', '.join(c + ' = %s' for c in columns)}"
                     " WHERE reference = %s", (*moved, reference))
    db.forget_cache()


def add_visits():
    """Five visits, one in each state the admin page counts."""
    guard = client.post("/api/admin/guards", headers={"X-Admin-Key": ADMIN_KEY},
                        json={"name": "Suresh", "phone": "+919000000005"}).get_json()
    suresh = {"X-Gate-Key": guard["key"]}
    photo = grey_photo()
    made_up = [
        ("Kavita Shah", "9820011223", "Delivery", "Main office", [], "closed", 180),
        ("Arjun Mehta", "9820044556", "See a student", "2024SEPVUGP0017", ["Neha Mehta"],
         "inside", 95),
        ("Farah Khan", "9820077889", "Event", "Music society", [], "declined", 70),
        ("Rohan Iyer", "9820022334", "See an office", "Admissions office", [], "approved", 40),
        ("Priya Desai", "9820055667", "See a student", "2023SEPVUGP0042", ["Anil Desai"],
         "pending", 5),
    ]
    for name, phone, reason, visiting, guests, state, minutes in made_up:
        made = client.post("/api/requests", json={
            "name": name, "phone": phone, "address": "Karjat, Raigad", "reason": reason,
            "visiting": visiting, "guests": guests}).get_json()
        reference = made["reference"]
        if state != "pending":
            say(APPROVER, f"{'NO' if state == 'declined' else 'YES'} {reference}")
        codes = visits.codes_of(reference)
        if state in ("inside", "closed"):
            client.post(f"/api/pass/{codes['entry']}/entry", headers=suresh, json=photo)
        if state == "closed":
            client.post(f"/api/pass/{codes['exit']}/exit", headers=suresh)
        move_back(reference, minutes)


def newest_reference():
    request = urllib.request.Request(f"{BASE}/api/admin/visits",
                                     headers={"X-Admin-Key": ADMIN_KEY})
    with urllib.request.urlopen(request) as answer:
        return json.load(answer)["visits"][0]["reference"]


# The pages scroll inside their own box, so a full-page picture stops at the
# window. The picture is cut at the bottom of the content instead.
BOTTOM = """sel => Math.max(...[...document.querySelectorAll(sel)]
    .map(n => n.getBoundingClientRect().bottom))"""


def save(page, folder, name, content="#view *"):
    page.wait_for_timeout(400)
    bottom = page.evaluate(BOTTOM, content)
    page.screenshot(path=os.path.join(folder, name), full_page=True,
                    clip={"x": 0, "y": 0, "width": page.viewport_size["width"],
                          "height": bottom + 24})
    print("saved", name)


def take_pictures(browser, folder):
    visitor = browser.new_context(**PHONE).new_page()
    visitor.goto(BASE + "/")
    visitor.wait_for_selector("text=Request a Visit")
    save(visitor, folder, "app-01-home.png")

    visitor.click("text=Request a Visit")
    visitor.fill("#f_name", "Meera Nair")
    visitor.fill("#f_phone", "9820088990")
    visitor.fill("#f_address", "Karjat, Raigad")
    visitor.click("text=Continue")
    visitor.click("#f_reason >> text=See a student")
    visitor.fill("#f_visiting", "2024SEPVUGP0003")
    visitor.click("#more")
    visitor.fill("#f_guest", "Nikhil Nair")
    visitor.press("#f_guest", "Enter")
    visitor.evaluate("document.activeElement.blur()")
    save(visitor, folder, "app-02-form.png")

    visitor.click("text=Review")
    visitor.click("text=Send request")
    visitor.wait_for_selector("text=Not approved yet")
    save(visitor, folder, "app-03-waiting.png")

    say(APPROVER, f"YES {newest_reference()}")
    visitor.wait_for_selector("h3:has-text('Approved')", timeout=20000)
    visitor.click("text=Open pass")
    visitor.wait_for_selector(".pass b")
    entry_code = visitor.inner_text(".pass b")
    save(visitor, folder, "app-04-pass.png")

    gate = browser.new_context(**PHONE)
    gate.add_init_script(f"localStorage.setItem('gatekey','{GATE_KEY}')")
    desk = gate.new_page()
    desk.goto(BASE + "/gate")
    desk.wait_for_selector("text=Inside now")
    desk.fill("#code", entry_code)
    desk.click("#look")
    desk.wait_for_selector("text=Let them in")
    save(desk, folder, "app-05-gate.png", "#out *")

    admin = browser.new_context(**DESKTOP)
    admin.add_init_script(f"localStorage.setItem('adminkey','{ADMIN_KEY}')")
    board = admin.new_page()
    board.goto(BASE + "/admin")
    board.wait_for_selector("text=Meera Nair")
    board.screenshot(path=os.path.join(folder, "app-06-admin.png"), full_page=True)
    print("saved app-06-admin.png")


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "pictures"
    os.makedirs(folder, exist_ok=True)
    db.init()
    add_visits()
    # One line per request would hide the six "saved" lines.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    server = make_server("127.0.0.1", PORT, application.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome")
            take_pictures(browser, folder)
            browser.close()
    finally:
        server.shutdown()
        db.close()
    print("The pictures are in", os.path.abspath(folder))


if __name__ == "__main__":
    main()

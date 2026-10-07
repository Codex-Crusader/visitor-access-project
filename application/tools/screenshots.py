"""Takes the README pictures with made-up visitors. See docs/maintenance.md.

Run from the app folder: .venv\\Scripts\\python.exe tools\\screenshots.py [folder]"""

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

from tests import testdb

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
# noinspection PyPackageRequirements
from werkzeug.serving import make_server

import app as application
from core import db
from core import checks
from models import visits
from services import whatsapp

try:
    # noinspection PyPackageRequirements
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

PORT = 5055
BASE = f"http://127.0.0.1:{PORT}"
GATE_KEY, ADMIN_KEY = "demo-gate-key-long-enough", "demo-admin-key-long-enough"
APPROVER = "919000000001"
PHONE = {"viewport": {"width": 428, "height": 1000}, "device_scale_factor": 2,
         "is_mobile": True, "has_touch": True, "locale": "en-IN", "timezone_id": "Asia/Kolkata",
         "reduced_motion": "reduce"}
# Reduced motion: no picture catches a color change halfway.
DESKTOP = {"viewport": {"width": 1100, "height": 900}, "device_scale_factor": 2,
           "locale": "en-IN", "timezone_id": "Asia/Kolkata", "reduced_motion": "reduce"}


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
    return {"photo": checks.PHOTO_PREFIX + base64.b64encode(out.getvalue()).decode()}


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


ADMIN = {"X-Admin-Key": ADMIN_KEY}
# Made-up offices, people and numbers only: no real person is in a picture.
OFFICES = [("Admissions Office", "+919000000011", "Main Building"),
           ("Accounts Office", "+919000000012", "Main Building"),
           ("Library", "+919000000013", "Library Block")]
STAFF = [("Dr Anita Rao", "+919000000021", "Faculty"),
         ("Prof Vikram Joshi", "+919000000022", "Faculty"),
         ("Sunita Pawar", "+919000000023", "Staff"),
         ("Ganesh More", "+919000000024", "Staff")]


def add_team():
    """Offices, an allow list with tags, and a blacklisted number. Returns the staff codes."""
    for name, phone, tag in OFFICES:
        client.post("/api/admin/offices", headers=ADMIN,
                    json={"name": name, "main": phone, "backup": "", "tag": tag})
    codes = {}
    for name, phone, tag in STAFF:
        made = client.post("/api/admin/staff", headers=ADMIN,
                           json={"name": name, "phone": phone, "tag": tag}).get_json()
        codes[name] = made["code"]
    client.post("/api/admin/blacklist", headers=ADMIN,
                json={"name": "Blocked Visitor", "phone": "+919000000099",
                      "reason": "Made-up entry for the pictures"})
    return codes


def add_visits(codes):
    """Five visits, one in each state the admin page counts, and two staff entries."""
    guard = client.post("/api/admin/guards", headers=ADMIN,
                        json={"name": "Suresh", "phone": "+919000000005"}).get_json()
    suresh = {"X-Gate-Key": guard["key"]}
    for name in ("Prof Vikram Joshi", "Sunita Pawar"):
        client.post(f"/api/staff/{codes[name]}/entry", headers=suresh)
    photo = grey_photo()
    made_up = [
        ("Kavita Shah", "9820011223", "Delivery", "Main office", [], "closed", 180),
        ("Arjun Mehta", "9820044556", "See a student", "2024SEPVUGP0017", ["Neha Mehta"],
         "inside", 95),
        ("Farah Khan", "9820077889", "Event", "Music society", [], "declined", 70),
        ("Rohan Iyer", "9820022334", "See an office", "Accounts Office", [], "approved", 40),
        ("Priya Desai", "9820055667", "See a student", "2023SEPVUGP0042", ["Anil Desai"],
         "pending", 5),
    ]
    for name, phone, reason, visiting, guests, state, minutes in made_up:
        office = visiting if reason == "See an office" else ""
        made = client.post("/api/requests", json={
            "name": name, "phone": phone, "address": "Karjat, Raigad", "reason": reason,
            "visiting": visiting, "office": office, "guests": guests}).get_json()
        reference = made["reference"]
        if state != "pending":
            decider = "919000000012" if reason == "See an office" else APPROVER
            say(decider, f"{'NO' if state == 'declined' else 'YES'} {reference}")
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


# The pages scroll in their own box, so cut the picture at the end of the content.
BOTTOM = """sel => Math.max(...[...document.querySelectorAll(sel)]
    .map(n => n.getBoundingClientRect().bottom))"""


def save(page, folder, name, content="#view *"):
    page.wait_for_timeout(400)
    bottom = page.evaluate(BOTTOM, content)
    page.screenshot(path=os.path.join(folder, name), full_page=True,
                    clip={"x": 0, "y": 0, "width": page.viewport_size["width"],
                          "height": bottom + 24})
    print("saved", name)


def take_pictures(browser, folder, codes):
    visitor = browser.new_context(**PHONE).new_page()
    visitor.goto(BASE + "/")
    visitor.wait_for_selector("text=Request a Visit")
    save(visitor, folder, "app-01-home.png")

    visitor.click("text=Request a Visit")
    visitor.fill("#f_name", "Meera Nair")
    visitor.fill("#f_phone", "9820088990")
    visitor.fill("#f_address", "Karjat, Raigad")
    visitor.click("text=Continue")
    visitor.click("#f_reason >> text=See an office")
    visitor.select_option("#f_office", "Admissions Office")
    visitor.click("#more")
    visitor.fill("#f_guest", "Nikhil Nair")
    visitor.press("#f_guest", "Enter")
    visitor.evaluate("document.activeElement.blur()")
    save(visitor, folder, "app-02-form.png")

    visitor.click("text=Review")
    visitor.click("text=Send request")
    visitor.wait_for_selector("text=Not approved yet")
    save(visitor, folder, "app-03-waiting.png")

    say("919000000011", f"YES {newest_reference()}")
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

    desk.click("text=Next visitor")
    desk.click("#modes >> text=Staff code")
    desk.fill("#code", codes["Dr Anita Rao"])
    desk.click("#look")
    desk.wait_for_selector("text=Entry recorded")
    save(desk, folder, "app-07-gate-staff.png", "#out *")

    admin = browser.new_context(**DESKTOP)
    admin.add_init_script(f"localStorage.setItem('adminkey','{ADMIN_KEY}')")
    board = admin.new_page()
    board.goto(BASE + "/admin")
    board.wait_for_selector("#t-list details")
    board.screenshot(path=os.path.join(folder, "app-06-admin.png"), full_page=True)
    print("saved app-06-admin.png")
    board.click("#tabs >> text=Allow list")
    board.wait_for_selector("#s-table >> text=Dr Anita Rao")
    board.screenshot(path=os.path.join(folder, "app-08-admin-allow.png"), full_page=True)
    print("saved app-08-admin-allow.png")


def main():
    if sync_playwright is None:
        sys.exit("playwright is not installed. Run:"
                 " .venv\\Scripts\\python.exe -m pip install playwright==1.63.0")
    folder = sys.argv[1] if len(sys.argv) > 1 else "pictures"
    os.makedirs(folder, exist_ok=True)
    db.init()
    codes = add_team()
    add_visits(codes)
    # One line per request would hide the "saved" lines.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    server = make_server("127.0.0.1", PORT, application.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome")
            take_pictures(browser, folder, codes)
            browser.close()
    finally:
        server.shutdown()
        db.close()
    print("The pictures are in", os.path.abspath(folder))


if __name__ == "__main__":
    main()

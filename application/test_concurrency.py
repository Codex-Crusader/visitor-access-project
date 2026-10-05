"""Hammer the app from many threads at once and check nothing corrupts."""

import base64
import io
import os
import threading
import time
from collections import Counter

import testdb

os.environ.update(
    META_TOKEN="t", META_PHONE_NUMBER_ID="1", META_VERIFY_TOKEN="v",
    META_APP_SECRET="", ALLOW_UNSIGNED_WEBHOOK="true", MAIN_APPROVER="+911234567890",
    BACKUP_APPROVER="+911234567890", GUARD="+911234567890",
    GATE_KEY="test-gate-key-long-enough", ADMIN_KEY="test-admin-key-long-enough",
    GATE_DESK_PHONE="+912200000000",
    ESCALATE_MINUTES="30", RETAIN_DAYS="1",
    # This suite tests database contention, not the rate limit.
    REQUESTS_PER_HOUR="100000", GATE_TRIES_PER_HOUR="100000",
    DATABASE_URL=testdb.url(),
)

from PIL import Image

import app as application
import db
import whatsapp

lock = threading.Lock()
sent = []
def fake_send(to, body):
    with lock:
        sent.append((to, body))
whatsapp.send = fake_send
whatsapp.send_template = lambda to, values: fake_send(to, "\n".join(values))

db.init()
# The cache works from the first call, so every race below runs through it.
db.CACHE_AFTER_SECONDS = 0
client =application.app.test_client()
KEY = {"X-Gate-Key": "test-gate-key-long-enough"}


def photo(shade=0):
    """A real gate page photo, one solid color, so the stored one can be told apart."""
    out = io.BytesIO()
    Image.new("RGB", (32, 32), (shade, 60, 200)).save(out, "JPEG")
    return {"photo": application.PHOTO_PREFIX + base64.b64encode(out.getvalue()).decode()}


def shade_of(data):
    """The red level of a stored photo: the shade it was taken with."""
    with Image.open(io.BytesIO(data)) as picture:
        pixel = picture.convert("RGB").getpixel((16, 16))
    assert isinstance(pixel, tuple), pixel
    return pixel[0]


N = 60
payload = {"name": "A", "phone": "9876543210", "address": "X",
           "reason": "See a student", "visiting": "S1", "guests": []}

# --- Many visitors submitting at the same moment ---
made = []
def submit():
    r = client.post("/api/requests", json=payload)
    with lock:
        made.append(r)

threads = [threading.Thread(target=submit) for _ in range(N)]
for t in threads:
    t.start()
for t in threads:
    t.join()

codes = [r.get_json()["reference"] for r in made if r.status_code == 201]
tokens = [r.get_json()["token"] for r in made if r.status_code == 201]
print(f"submitted {N} at once -> {len(codes)} created, {N - len(codes)} failed")
assert len(codes) == N, [r.status_code for r in made if r.status_code != 201][:3]
assert len(set(codes)) == N, f"duplicate codes: {[c for c, n in Counter(codes).items() if n > 1]}"
assert len(set(tokens)) == N, "duplicate tokens"
gate_codes = [c for ref in codes for c in db.codes_of(ref).values()]
assert len(gate_codes) == 2 * N and len(set(gate_codes)) == 2 * N, "missing or shared gate codes"
print("  every code unique, every token unique, two gate codes each")

# --- Approve them all at once ---
def approve(code):
    db.decide(code, db.APPROVED, db.BY_MAIN)

threads = [threading.Thread(target=approve, args=(c,)) for c in codes]
for t in threads:
    t.start()
for t in threads:
    t.join()
assert all(db.get(c)["status"] == "approved" for c in codes)
print("  all approved under load")

# --- Twenty guards racing to check the SAME visitor in ---
target = codes[0]
results = []
def race(action):
    """Twenty guards press the same button on the same pass at once."""
    results.clear()
    code = db.codes_of(target)[action]
    def press():
        r = client.post(f"/api/pass/{code}/{action}", headers=KEY, json=photo())
        with lock:
            results.append(r.status_code)
    racers = [threading.Thread(target=press) for _ in range(20)]
    for racer in racers:
        racer.start()
    for racer in racers:
        racer.join()

race("entry")
wins = results.count(200)
print(f"  20 guards raced one entry -> {wins} accepted, {results.count(409)} refused")
assert wins == 1, f"entry must happen exactly once, got {wins}"
assert db.get(target)["status"] == "inside"

# --- Racing exits on the same visitor ---
race("exit")
print(f"  20 guards raced one exit  -> {results.count(200)} accepted, {results.count(409)} refused")
assert results.count(200) == 1
assert db.get(target)["status"] == "closed"

# --- Many different visitors entering and exiting at once ---
busy = codes[1:41]
def cycle(reference):
    pass_codes = db.codes_of(reference)
    client.post(f"/api/pass/{pass_codes['entry']}/entry", headers=KEY, json=photo())
    client.post(f"/api/pass/{pass_codes['exit']}/exit", headers=KEY)
threads = [threading.Thread(target=cycle, args=(c,)) for c in busy]
for t in threads:
    t.start()
for t in threads:
    t.join()
closed = [c for c in busy if db.get(c)["status"] == "closed"]
print(f"  {len(busy)} visitors in and out at once -> {len(closed)} closed correctly")
assert len(closed) == len(busy)
stamps = [(db.get(c)["entered_at"], db.get(c)["exited_at"]) for c in busy]
assert all(a and b for a, b in stamps), "every visit must have both timestamps"

# --- Duplicate webhook deliveries arriving concurrently ---
def inbound(mid, text):
    return {"entry": [{"changes": [{"value": {"messages": [
        {"id": mid, "from": "911234567890", "type": "text", "text": {"body": text}}]}}]}]}

sent.clear()
same = inbound("wamid.race", f"YES {codes[50]}")
threads = [threading.Thread(target=lambda: client.post("/webhook/whatsapp", json=same))
           for _ in range(15)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print(f"  same message delivered 15x -> {len(sent)} replies sent")
assert len(sent) <= 1, f"duplicate message must act at most once, sent {len(sent)}"

# --- Twenty guards with their own keys, added at once ---
ADMIN = {"X-Admin-Key": "test-admin-key-long-enough"}
guard_phones = [f"+9198000{n:05d}" for n in range(20)]
added = []
def add_guard(n):
    r = client.post("/api/admin/guards", json={"name": f"Guard {n}", "phone": guard_phones[n]},
                    headers=ADMIN)
    with lock:
        added.append(r)
threads = [threading.Thread(target=add_guard, args=(n,)) for n in range(20)]
for t in threads:
    t.start()
for t in threads:
    t.join()
assert all(r.status_code == 200 for r in added), [r.status_code for r in added]
guard_keys = {r.get_json()["name"]: r.get_json()["key"] for r in added}
# Each guard's photo has its own color, 12 apart, so the stored one names its guard.
SHADES = {f"Guard {n}": 12 * n for n in range(20)}
assert len(set(guard_keys.values())) == 20, "every guard key unique"
assert len(db.guards()) == 20
print("  20 guards added at once -> 20 unique keys")

# --- The same twenty race one entry, each with their own key ---
def fresh_approved(count):
    answers = [client.post("/api/requests", json=payload) for _ in range(count)]
    new_refs = [r.get_json()["reference"] for r in answers]
    for ref in new_refs:
        db.decide(ref, db.APPROVED, db.BY_MAIN)
    return new_refs

target = fresh_approved(1)[0]
entry = db.codes_of(target)["entry"]
winners = []
def own_press(name):
    r = client.post(f"/api/pass/{entry}/entry", headers={"X-Gate-Key": guard_keys[name]},
                    json=photo(SHADES[name]))
    with lock:
        winners.append((r.status_code, name))
threads = [threading.Thread(target=own_press, args=(name,)) for name in guard_keys]
for t in threads:
    t.start()
for t in threads:
    t.join()
won = [name for status, name in winners if status == 200]
print(f"  20 own keys raced one entry -> {len(won)} accepted")
assert len(won) == 1, won
phone = guard_phones[int(won[0].split()[1])]
assert db.get(target)["entered_by"] == f"{won[0]} {phone}", "the winner is the guard on record"
assert abs(shade_of(db.photo_of(target)["image"]) - SHADES[won[0]]) <= 6, \
    "only the winner's photo is kept"

# --- Each guard lets a different visitor in and out at once ---
refs = fresh_approved(20)
def own_cycle(n):
    pass_codes = db.codes_of(refs[n])
    headers = {"X-Gate-Key": guard_keys[f"Guard {n}"]}
    client.post(f"/api/pass/{pass_codes['entry']}/entry", headers=headers, json=photo())
    client.post(f"/api/pass/{pass_codes['exit']}/exit", headers=headers)
tokens = [db.get(ref)["token"] for ref in refs]
racing = threading.Event()
def watch(start):
    """Visitors' pages and the gate board, polling while the guards work.

    Five pages with a short pause, as real pages do. Twenty tight loops would
    need more connections than the server's four threads ever use.
    """
    while racing.is_set():
        for token in tokens[start::5]:
            client.get(f"/api/visit/{token}")
        client.get("/api/gate/board", headers=KEY)
        time.sleep(0.02)
racing.set()
watchers = [threading.Thread(target=watch, args=(start,)) for start in range(5)]
threads = [threading.Thread(target=own_cycle, args=(n,)) for n in range(20)]
for t in watchers + threads:
    t.start()
for t in threads:
    t.join()
racing.clear()
for t in watchers:
    t.join()
for n, ref in enumerate(refs):
    visit = db.get(ref)
    label = f"Guard {n} {guard_phones[n]}"
    assert visit["status"] == "closed", visit["status"]
    assert visit["entered_by"] == label and visit["exited_by"] == label, visit
# The polls filled the cache during the race. None of it may be stale now.
stale = [token for token in tokens
         if client.get(f"/api/visit/{token}").get_json()["status"] != "closed"]
assert not stale, f"{len(stale)} cached passes are stale"
board = client.get("/api/gate/board", headers=KEY).get_json()
on_board = {v["reference"] for v in board["expected"] + board["inside"]}
assert not on_board & set(refs), "a closed visit is still on the cached board"
print("  20 guards, 20 visitors in and out at once -> each visit names its own guard")
print("  5 pages polling the 20 passes during the race -> no cached pass or board row is stale")

# --- Ten approvals at once, each told to every guard ---
sent.clear()
pending = [client.post("/api/requests", json=payload).get_json()["reference"] for _ in range(10)]
sent.clear()
threads = [threading.Thread(target=lambda ref=ref: client.post(
               "/webhook/whatsapp", json=inbound(f"wamid.{ref}", f"YES {ref}")))
           for ref in pending]
for t in threads:
    t.start()
for t in threads:
    t.join()
assert all(db.get(ref)["status"] == "approved" for ref in pending)
for guard_phone in guard_phones:
    told = [body for to, body in sent if to == guard_phone]
    assert len(told) == 10, (guard_phone, len(told))
    assert {ref for ref in pending if any(ref in body for body in told)} == set(pending)
print("  10 approvals at once -> each of 20 guards told about each one exactly once")

print()
print("concurrency checks passed")

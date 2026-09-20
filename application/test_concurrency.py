"""Hammer the app from many threads at once and check nothing corrupts."""

import os
import tempfile
import threading
from collections import Counter

os.environ.update(
    META_TOKEN="t", META_PHONE_NUMBER_ID="1", META_VERIFY_TOKEN="v",
    META_APP_SECRET="", MAIN_APPROVER="+911234567890",
    BACKUP_APPROVER="+911234567890", GUARD="+911234567890",
    GATE_KEY="k", GATE_DESK_PHONE="+912200000000",
    ESCALATE_MINUTES="30", RETAIN_DAYS="1",
    # This suite tests database contention, not the rate limit.
    REQUESTS_PER_HOUR="100000", GATE_TRIES_PER_HOUR="100000",
    DATABASE_PATH=os.path.join(tempfile.mkdtemp(), "load.db"),
)

import app as application
import db
import whatsapp

lock = threading.Lock()
sent = []
def fake_send(to, body):
    with lock:
        sent.append((to, body))
whatsapp.send = fake_send

db.init()
client = application.app.test_client()
KEY = {"X-Gate-Key": "k"}

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
for t in threads: t.start()
for t in threads: t.join()

codes = [r.get_json()["reference"] for r in made if r.status_code == 201]
tokens = [r.get_json()["token"] for r in made if r.status_code == 201]
print(f"submitted {N} at once -> {len(codes)} created, {N - len(codes)} failed")
assert len(codes) == N, [r.status_code for r in made if r.status_code != 201][:3]
assert len(set(codes)) == N, f"duplicate codes: {[c for c, n in Counter(codes).items() if n > 1]}"
assert len(set(tokens)) == N, "duplicate tokens"
print("  every code unique, every token unique")

# --- Approve them all at once ---
def approve(code):
    db.decide(code, db.APPROVED)

threads = [threading.Thread(target=approve, args=(c,)) for c in codes]
for t in threads: t.start()
for t in threads: t.join()
assert all(db.get(c)["status"] == "approved" for c in codes)
print("  all approved under load")

# --- Twenty guards racing to check the SAME visitor in ---
target = codes[0]
results = []
def race_in():
    r = client.post(f"/api/pass/{target}/entry", headers=KEY)
    with lock:
        results.append(r.status_code)

threads = [threading.Thread(target=race_in) for _ in range(20)]
for t in threads: t.start()
for t in threads: t.join()
wins = results.count(200)
print(f"  20 guards raced one entry -> {wins} accepted, {results.count(409)} refused")
assert wins == 1, f"entry must happen exactly once, got {wins}"
assert db.get(target)["status"] == "inside"

# --- Racing exits on the same visitor ---
results.clear()
def race_out():
    r = client.post(f"/api/pass/{target}/exit", headers=KEY)
    with lock:
        results.append(r.status_code)
threads = [threading.Thread(target=race_out) for _ in range(20)]
for t in threads: t.start()
for t in threads: t.join()
print(f"  20 guards raced one exit  -> {results.count(200)} accepted, {results.count(409)} refused")
assert results.count(200) == 1
assert db.get(target)["status"] == "closed"

# --- Many different visitors entering and exiting at once ---
busy = codes[1:41]
def cycle(code):
    client.post(f"/api/pass/{code}/entry", headers=KEY)
    client.post(f"/api/pass/{code}/exit", headers=KEY)
threads = [threading.Thread(target=cycle, args=(c,)) for c in busy]
for t in threads: t.start()
for t in threads: t.join()
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
threads = [threading.Thread(target=lambda: client.post("/webhook/whatsapp", json=same)) for _ in range(15)]
for t in threads: t.start()
for t in threads: t.join()
print(f"  same message delivered 15x -> {len(sent)} replies sent")
assert len(sent) <= 1, f"duplicate message must act at most once, sent {len(sent)}"

print()
print("concurrency checks passed")

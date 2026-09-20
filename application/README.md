# Campus Visitor Access

A visitor fills in a web form. The server sends the details to an approver on
WhatsApp. The approver replies YES or NO. The visitor sees the decision on the
same page within three seconds. At the gate, a guard checks the code, records
the entry and the exit, and the code then stops working.

The guard works either from a web page or from WhatsApp.

## How it works

1. The browser posts the form to `POST /api/requests`.
2. The server stores the request and gives it two things: a short code like
   `VR-4022` that people read aloud, and a long private token for the browser.
3. The server sends one WhatsApp message to the main approver.
4. The approver replies `YES VR-4022` or `NO VR-4022`.
5. Meta posts that reply to `POST /webhook/whatsapp`.
6. The server records the decision.
7. The visitor's page asks `GET /api/visit/<token>` every three seconds.
8. At the gate, the guard records entry and exit.

If no reply arrives within `ESCALATE_MINUTES`, the server sends the same details
to the backup approver. Escalation never decides anything. Only a YES or a NO
changes the status.

## The life of a pass

Each arrow happens once and cannot be undone.

```
pending ──(no reply in time)──> escalated
   │                                │
   └──────(YES / NO reply)──────────┘
                 │
        approved │ declined
                 │
         (guard records entry)
                 │
              inside
                 │
         (guard records exit)
                 │
              closed
```

A closed code is dead. Nothing works on it again.

## WhatsApp commands

One phone number can be the approver, the backup approver and the guard at the
same time, so each job has its own word.

| You send | What happens |
| --- | --- |
| `VR-4022` | Shows the pass and says what you can do next |
| `YES VR-4022` | Approves the request |
| `NO VR-4022` | Declines the request |
| `IN VR-4022` | Records the entry |
| `OUT VR-4022` | Records the exit |
| anything else | Sends back the request that is waiting, with full details |

`YES` and `NO` work without a code when exactly one request is waiting. The
server ignores every number that is not in `MAIN_APPROVER`, `BACKUP_APPROVER`
or `GUARD`.

## Two kinds of address, on purpose

The short code has only 9,000 possibilities, so it is not a secret. Anyone could
guess one. The code therefore never opens anything on its own.

- The visitor's browser reads `GET /api/visit/<token>`. The token is 22
  characters of random text, so nobody can guess another visitor's request.
- The gate reads and writes `/api/pass/<code>`, and every one of those calls
  needs the `X-Gate-Key` header. The guard types that key once on the gate page.

## The visit log

Every request keeps its own row, including the exact times it was approved, the
visitor entered, and the visitor left. The gate page has a **Download visit log**
button that saves the whole history as a CSV file, and the same data is at
`GET /api/export.csv` with the `X-Gate-Key` header.

The CSV has one row per visit and these columns:

```
reference, name, phone, address, reason, visiting, guests,
status, created_at, escalated_at, decided_at, entered_at, exited_at
```

Times are UTC in ISO format. A visit that never entered has empty `entered_at`
and `exited_at`, so you can filter completed visits on those columns.

Records are deleted `RETAIN_DAYS` after they are created, 90 days by default.
The privacy screen in the visitor app states that same number, so the promise and
the code agree. Change one and change the other.

## Files

| File | What it holds |
| --- | --- |
| `app.py` | Flask routes, the escalation timer and the delete timer |
| `db.py` | SQLite storage |
| `whatsapp.py` | Meta API send, message text, command reading |
| `config.py` | Settings read from the environment |
| `check_setup.py` | Checks your settings and sends one test message |
| `test_app.py` | Runs the whole flow with WhatsApp stubbed out |
| `test_concurrency.py` | Hammers the app from many threads to check the races |
| `static/index.html`, `static/app.js` | The visitor app |
| `static/gate.html`, `static/gate.js` | The gate desk page |
| `render.yaml`, `Procfile` | How the host starts the app |

## Settings

| Name | What it is |
| --- | --- |
| `META_TOKEN` | Access token from the WhatsApp API Setup page |
| `META_PHONE_NUMBER_ID` | Phone number ID from the same page |
| `META_VERIFY_TOKEN` | Any text. Type the same text into the Meta webhook page |
| `META_APP_SECRET` | App secret. Leave empty to skip the signature check |
| `MAIN_APPROVER` | Approver number, like `+911234567890` |
| `BACKUP_APPROVER` | Backup approver. Defaults to the main approver |
| `GUARD` | Gate desk number. Defaults to the main approver |
| `GATE_KEY` | Password for the gate page. Keep it off the internet |
| `GATE_DESK_PHONE` | Number shown on the "Call gate desk" button |
| `ESCALATE_MINUTES` | Minutes before the backup approver is asked. Default 30 |
| `RETAIN_DAYS` | Days a record is kept before deletion. Default 90 |

Write every phone number in E.164 form: a plus sign, the country code, then the
number. Each approver number must also be on the recipient list in the Meta API
Setup page, because a test number only sends to numbers on that list.

## Run it on your own machine

```
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

Fill in `.env`, then check it. This sends one message to your phone.

```
.venv\Scripts\python.exe check_setup.py
```

Start the server.

```
.venv\Scripts\python.exe app.py
```

The visitor app is at http://127.0.0.1:5000 and the gate desk is at
http://127.0.0.1:5000/gate.

Meta must reach your webhook from the internet, so open a tunnel in a second
terminal.

```
cloudflared tunnel --url http://localhost:5000
```

Put the printed address plus `/webhook/whatsapp` into the Meta Configuration
page, with your `META_VERIFY_TOKEN`, and press Verify and save. Then switch the
**messages** field to Subscribed. The app receives nothing until you do that.
It is the step people miss.

## Put it on the internet with Render

1. Push this folder to GitHub. `.env` and `visits.db` stay out, see `.gitignore`.
2. On https://render.com, choose New, then Web Service, and pick the repository.
3. Render reads `render.yaml`. Leave the build and start commands alone.
4. Fill in every setting from the table above in the Environment section.
5. Deploy. Render gives you an address like
   `https://visitor-access.onrender.com`.
6. Put that address plus `/webhook/whatsapp` into the Meta Configuration page
   and subscribe the **messages** field again. This address does not change, so
   this is the last time you do it.

Use a permanent access token, not the temporary one. The temporary token stops
working after about 24 hours and your live app dies with it. Make a permanent
one in Meta Business settings, under Users, then System users: add a system
user, give it your app with full control, then Generate token with the
`whatsapp_business_messaging` and `whatsapp_business_management` permissions,
and choose Never for expiry.

### What the free plan costs you

- The service sleeps after 15 minutes with no traffic and takes about 30 seconds
  to wake. The first WhatsApp reply after a nap can be slow. Meta retries, and
  the app ignores repeated messages, so nothing happens twice.
- While the service sleeps, the escalation timer does not run. A request that
  should escalate does so once the service wakes.
- `visits.db` is wiped on every redeploy, because the free plan has no disk.
  Records also delete themselves after `RETAIN_DAYS`, so this only matters if
  you redeploy in the middle of a demo.

## Demo run

1. Open your address and send a request.
2. Read the WhatsApp message on your phone.
3. Reply `YES VR-4022`, using the code from the message.
4. Watch the page turn green and show the entry pass.
5. Send `IN VR-4022` on WhatsApp, or use `/gate` in a browser.
6. The visitor page changes to "Inside campus" by itself.
7. Send `OUT VR-4022`. The visitor page says "Visit complete".
8. Send the code once more. It says the pass is closed.

To show a decline, reply `NO` with the code.

To show escalation, set `ESCALATE_MINUTES=1` and restart. Send a request and do
not reply. After one minute the backup approver gets the same details.

## When something fails

- Error 190: the access token expired. Use a permanent token, see above.
- Error 131030: the number is not on the Meta recipient list. Add it.
- The reply never changes the page: the webhook address does not match your
  current address, or the **messages** field is not subscribed.
- The webhook returns 403: `META_APP_SECRET` does not match the app.
- The gate page says "Wrong gate key": clear the key in the browser and type it
  again.

## Checks

```
.venv\Scripts\python.exe test_app.py
```

```
.venv\Scripts\python.exe test_concurrency.py
```

The first runs the whole flow without sending any WhatsApp message: approval,
decline, escalation, repeated deliveries, the code-guessing defence, both gate
routes, the export, and the delete-after-retention rule.

The second proves the app survives load: sixty visitors submitting at the same
instant all get unique codes, and twenty guards pressing Record entry on the same
visitor produce exactly one entry, not twenty.

## Known limits

- The gate key is one shared password. Every guard uses the same one, and there
  is no record of which guard pressed the button. It also unlocks the full export,
  so anyone with the key can download every visitor's name, phone and address.
- The approver is one fixed number. A real deployment would look up the student
  being visited and message that person.
- The 4-digit code is short enough to guess, which is why it never works on its
  own. Do not make it do more than it does here.

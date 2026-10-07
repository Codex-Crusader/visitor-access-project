# Campus Visitor Access

> ## Documentation
>
> | Document                                                       | Read it to                                               |
> |----------------------------------------------------------------|----------------------------------------------------------|
> | [docs/setup.md](docs/setup.md)                                 | Set up a new copy, and learn each setting                |
> | [docs/maintenance.md](docs/maintenance.md)                     | Use the app each day, and deploy, watch and repair it    |
> | [docs/safety.md](docs/safety.md)                               | Know what the app protects, and its known limits         |
> | [docs/university-deployment.md](docs/university-deployment.md) | Decide on real use: hosting, data, roles, outages, pilot |

A visitor fills in a web form. The server sends the details to an approver on
WhatsApp. The approver replies YES or NO. The visitor sees the decision on the
same page a few seconds later. At the gate, the guard checks the entry code
on the visitor's pass, takes a photo and records the entry. On the way out,
the pass shows a different code, the exit code, and the guard uses it to
record the exit. After that, neither code works.

The guard works from a web page or from WhatsApp, and gets a WhatsApp message
when a request is approved. The admin reads every request on an admin page,
and manages the guards, the other admins, the offices, the allow list and
the blacklist there. Each
guard and admin has a key of their own, so the log names who let each
visitor in and out.

A visitor who picks See an office then picks an office from a list, and the
request goes to that office's own approver. Staff and faculty on the allow
list do not send a request: they say their 7-digit code to the guard,
the guard sends it on WhatsApp or types it on the gate page, and the entry is
recorded at once. The person gets a WhatsApp message about the entry. A
number on the blacklist cannot request a visit or enter.

## How it works

1. The browser posts the form to `POST /api/requests`.
2. The server stores the request and gives it four things: a reference such
   as `VR-40221` for the approvers, an entry code and an exit code such as
   `KT-4821` for the gate, and a long private token for the browser.
3. The server sends one WhatsApp template message to the main approver for
   the request's office, or else for its reason.
4. The approver replies `YES VR-40221` or `NO VR-40221`.
5. Meta posts that reply to `POST /webhook/whatsapp`, and the server records
   the decision and the number that made it.
6. The visitor's page asks `GET /api/visit/<token>` every 5 seconds while it
   waits for the decision, then less often. An unchanged answer is a 304
   with an empty body, so the page uses little data on a weak signal.
7. At the gate, the guard sends `IN` and the entry code, then a photo of the
   visitor. The photo records the entry. Later, `OUT` and the exit code
   record the exit.

If nobody answers in `ESCALATE_MINUTES`, the server sends the same details to
the backup approver, or, when there is no backup, a reminder to the approver. In working hours, the server approves a request that
nobody answers in `AUTO_APPROVE_MINUTES`. A pass works for `PASS_HOURS` after
the request.

## The life of a pass

Each arrow happens once and cannot be undone.

```
pending ──(no reply in time)──> escalated
   │                                │
   └──(YES / NO, or auto-approval)──┘
                 │
        approved │ declined
                 │                  (no entry in PASS_HOURS) ──> expired
   (guard sends IN and the entry code, then a photo)
                 │
              inside
                 │
   (guard records exit with the exit code)
                 │
              closed
```

A pending, escalated or approved request becomes expired `PASS_HOURS` after
the request. A closed pass is dead. Neither code works on it again, and the
gate sees only its times.

## The API

| Address                             | Key            | Does                                     |
|-------------------------------------|----------------|------------------------------------------|
| `POST /api/requests`                | none           | Makes a request                          |
| `GET /api/visit/<token>`            | the token      | The visitor's own request                |
| `GET /api/config`                   | none           | The settings that the visitor page shows |
| `GET /api/health`                   | none           | 200 or 503, for the uptime check         |
| `GET /api/pass/<code or reference>` | `X-Gate-Key`   | Shows a pass at the gate                 |
| `POST /api/pass/<code>/<action>`    | `X-Gate-Key`   | Records an entry or an exit              |
| `GET /api/gate/board`               | `X-Gate-Key`   | The Inside now and Expected lists        |
| `GET /api/staff/<code>`             | `X-Gate-Key`   | The name for an allow list code          |
| `POST /api/staff/<code>/entry`      | `X-Gate-Key`   | Records an allow list entry              |
| `GET /api/admin/visits`             | `X-Admin-Key`  | One page of requests, newest first       |
| `GET /api/admin/summary`            | `X-Admin-Key`  | Counts, approvers and rules              |
| `POST /api/admin/approvers`         | `X-Admin-Key`  | Changes one reason's two approvers       |
| `POST /api/admin/<list>`            | `X-Admin-Key`  | Adds to one of the lists below           |
| `POST /api/admin/<list>/remove`     | `X-Admin-Key`  | Deletes one from that list               |
| `POST /api/admin/<list>/new-key`    | `X-Admin-Key`  | A new key for a guard or an admin        |
| `POST /api/admin/<list>/tag`        | `X-Admin-Key`  | A new tag for one office or person       |
| `POST /api/admin/tags/rename`       | `X-Admin-Key`  | Renames a tag on every row of a list     |
| `POST /api/admin/decide`            | super admin    | Approves or declines up to 100 requests  |
| `POST /api/admin/admins/super`      | super admin    | Makes an admin a super admin, or not     |
| `GET /api/admin/export.csv`         | `X-Admin-Key`  | The whole visit log                      |
| `GET /api/admin/export.zip`         | `X-Admin-Key`  | The logs, photos and a page with both    |
| `POST /api/forgot-key/<which>`      | none           | Sends a key to its fixed WhatsApp number |
| `GET /webhook/whatsapp`             | verify token   | Meta's one-time check of the address     |
| `POST /webhook/whatsapp`            | Meta signature | Replies and photos from WhatsApp         |

In `/api/pass/<code>/<action>`, the action is `entry` or `exit`. In
`/api/forgot-key/<which>`, it is `gate` or `admin`. In `/api/admin/<list>`, the
list is `guards`, `admins`, `offices`, `staff` (the allow list) or
`blacklist`. The pages are `/` for the
visitor, `/gate` for the guard and `/admin` for the admin.

## Files

| File                                   | What it holds                                                          |
|----------------------------------------|------------------------------------------------------------------------|
| `docs/`                                | Setup, maintenance, safety, and every WhatsApp message                 |
| `app.py`                               | Makes the Flask app, adds the security headers, starts the timer       |
| `routes/visitor.py`                    | The visitor page's calls: a new request and its status                 |
| `routes/gate.py`                       | The gate page's calls: look up a pass, the board, entry and exit       |
| `routes/admin.py`                      | The admin page's calls, and the forgotten-key messages                 |
| `routes/team.py`                       | The admin page's lists: guards, admins, offices, allow list, blacklist |
| `routes/webhook.py`                    | The WhatsApp webhook: decisions, entry and exit by message             |
| `pages.py`                             | Serves the three pages, the script versions and the header values      |
| `checks.py`                            | Checks the form fields, phone numbers and gate photos                  |
| `access.py`                            | The keys, and who is an approver, a guard or an admin                  |
| `limits.py`                            | How often one address may call the public addresses                    |
| `notify.py`                            | Messages the app sends by itself, such as approvals to the guards      |
| `timer.py`                             | Escalation, automatic approval, expiry and the purge                   |
| `db.py`                                | The Postgres connections, the read cache, and the stored values        |
| `migrations.py`                        | The schema changes, in order                                           |
| `visits.py`                            | The queries for requests, codes, decisions and the page lists          |
| `entries.py`                           | The queries for entries, exits and gate photos                         |
| `people.py`                            | The queries for approvers, offices, guards and admins                  |
| `staff.py`                             | The queries for the allow list and its entries                         |
| `blacklist.py`                         | The queries for the blacklist and the attempts it stopped              |
| `export.py`                            | The log as CSV, and the ZIP with the photos                            |
| `audit.py`                             | The admin change log: who changed what, never a key                    |
| `tags.py`                              | The tags that group the offices and the allow list                     |
| `whatsapp.py`                          | Meta API calls, message text, and command reading                      |
| `config.py`                            | Settings read from the environment                                     |
| `gunicorn.conf.py`                     | Starts and stops the database and timer in the worker                  |
| `render.yaml`                          | A record of the Render settings                                        |
| `static/index.html`, `static/app.js`   | The visitor page                                                       |
| `static/gate.html`, `static/gate.js`   | The gate desk page                                                     |
| `static/admin.html`, `static/admin.js` | The admin page                                                         |
| `static/shared.js`                     | The CSV download for admin, and the forgot-key call for gate and admin |
| `static/sw.js`                         | Keeps the visitor page on the phone, so it opens offline               |
| `run_tests.py`                         | Runs every test and both linters with one command                      |
| `tests/test_*.py`                      | Run the whole flow with WhatsApp stubbed out, one topic a file         |
| `tests/kit.py`                         | The settings, clean database and helpers that the tests share          |
| `tests/test_concurrency.py`            | Makes many calls at once to check the races                            |
| `tests/test_form.js`                   | Checks the three pages in a real DOM with jsdom                        |
| `tests/testdb.py`                      | Starts a throwaway Postgres for the Python tests                       |
| `tools/check_setup.py`                 | Checks your settings and sends one test message                        |
| `ruff.toml`, `eslint.config.mjs`       | Linter settings, and why some rules are off                            |
| `tools/whatsapp_messages.py`           | Writes docs/whatsapp-messages.md by running the app                    |

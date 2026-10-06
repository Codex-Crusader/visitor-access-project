# Campus Visitor Access

> ## Documentation
>
> | Document                                   | Read it to                                            |
> |--------------------------------------------|-------------------------------------------------------|
> | [docs/setup.md](docs/setup.md)             | Set up a new copy, and learn each setting             |
> | [docs/maintenance.md](docs/maintenance.md) | Use the app each day, and deploy, watch and repair it |
> | [docs/safety.md](docs/safety.md)           | Know what the app protects, and its known limits      |

A visitor fills in a web form. The server sends the details to an approver on
WhatsApp. The approver replies YES or NO. The visitor sees the decision on the
same page a few seconds later. At the gate, the guard checks the entry code
on the visitor's pass, takes a photo and records the entry. On the way out,
the pass shows a different code, the exit code, and the guard uses it to
record the exit. After that, neither code works.

The guard works from a web page or from WhatsApp, and gets a WhatsApp message
when a request is approved. The admin reads every request on an admin page,
and adds the guards there. Each guard has a key of their own, so the log
names who let each visitor in and out.

## How it works

1. The browser posts the form to `POST /api/requests`.
2. The server stores the request and gives it four things: a reference such
   as `VR-40221` for the approvers, an entry code and an exit code such as
   `KT-4821` for the gate, and a long private token for the browser.
3. The server sends one WhatsApp template message to the main approver for
   the request's reason.
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
the backup approver. In working hours, the server approves a request that
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
| `GET /api/admin/visits`             | `X-Admin-Key`  | One page of requests, newest first       |
| `GET /api/admin/summary`            | `X-Admin-Key`  | Counts, approvers and rules              |
| `POST /api/admin/approvers`         | `X-Admin-Key`  | Changes one reason's two approvers       |
| `GET /api/admin/export.csv`         | `X-Admin-Key`  | The whole visit log                      |
| `POST /api/forgot-key/<which>`      | none           | Sends a key to its fixed WhatsApp number |
| `GET /webhook/whatsapp`             | verify token   | Meta's one-time check of the address     |
| `POST /webhook/whatsapp`            | Meta signature | Replies and photos from WhatsApp         |

In `/api/pass/<code>/<action>`, the action is `entry` or `exit`. In
`/api/forgot-key/<which>`, it is `gate` or `admin`. The pages are `/` for the
visitor, `/gate` for the guard and `/admin` for the admin.

## Files

| File                                   | What it holds                                                          |
|----------------------------------------|------------------------------------------------------------------------|
| `docs/`                                | Setup, maintenance and safety                                          |
| `app.py`                               | Flask routes, the security headers and the background timer            |
| `db.py`                                | The Postgres connections, the read cache, and the stored values        |
| `migrations.py`                        | The schema changes, in order                                           |
| `visits.py`                            | The queries for requests, codes, decisions and the page lists          |
| `entries.py`                           | The queries for entries, exits and gate photos                         |
| `people.py`                            | The queries for approvers and guards                                   |
| `whatsapp.py`                          | Meta API calls, message text, and command reading                      |
| `config.py`                            | Settings read from the environment                                     |
| `check_setup.py`                       | Checks your settings and sends one test message                        |
| `gunicorn.conf.py`                     | Starts and stops the database and timer in the worker                  |
| `render.yaml`                          | A record of the Render settings                                        |
| `static/index.html`, `static/app.js`   | The visitor page                                                       |
| `static/gate.html`, `static/gate.js`   | The gate desk page                                                     |
| `static/admin.html`, `static/admin.js` | The admin page                                                         |
| `static/shared.js`                     | The CSV download for admin, and the forgot-key call for gate and admin |
| `static/sw.js`                         | Keeps the visitor page on the phone, so it opens offline               |
| `test_app.py`                          | Runs the whole flow with WhatsApp stubbed out                          |
| `test_concurrency.py`                  | Makes many calls at once to check the races                            |
| `run_tests.py`                         | Runs every test and both linters with one command                      |
| `test_form.js`                         | Checks the three pages in a real DOM with jsdom                        |
| `testdb.py`                            | Starts a throwaway Postgres for the two Python tests                   |
| `ruff.toml`, `eslint.config.mjs`       | Linter settings, and why some rules are off                            |

# Campus Visitor Access

A visitor fills in a web form. The server sends the details to an approver on
WhatsApp. The approver replies YES or NO. The visitor sees the decision on the
same page within three seconds. At the gate, the guard checks the entry code
on the visitor's pass, takes a photo and records the entry. On the way out, the
pass shows a different code, the exit code, and the guard uses it to record the
exit. After that, neither code works.

The guard works either from a web page or from WhatsApp.

## The gate page

The gate page at `/gate` asks for the gate key once. After that it shows:

1. A box for the code on the visitor's pass.
2. **Inside now**: everyone who entered and has not left, longest first. A
   visitor inside for more than 8 hours has a yellow row, so a visitor who
   never checked out is easy to see.
3. **Expected**: every pass approved in the last 24 hours and not used yet.
   An older pass still works. It only leaves this list.
4. **Refresh the lists**, **Download log** and **Change gate key**.

Tap a name to see who it is. A tap records nothing. To record an entry or an
exit, type the code on the visitor's pass. The lists
refresh every 30 seconds and after every entry or exit. When a refresh fails,
the page keeps the last lists and says how old they are. A wrong gate key is
named as the reason.

The lists come from `GET /api/gate/board` with the `X-Gate-Key` header. It
returns only open visits, and for each one only the reference, name, person
visited, guests, status and the approval and entry times. `BOARD_HOURS` and
`LONG_HOURS` set the 24 and 8 hours, in `app.py` and `static/gate.js`.

The badge in the top corner says Live while the lists are fresh and Offline
after a refresh fails. If the saved gate key is wrong, the page forgets it and
asks for the key again. The page follows the phone's light or dark setting.

## Forgotten keys

The gate page and the admin page each have a "Forgot ... key?" button under
the key box. It sends the key by WhatsApp to one fixed number: the gate key to
`GUARD`, the admin key to `ADMIN_PHONE`. The page shows only the last four
digits of that number, never the key.

WhatsApp delivers this plain text only if that number wrote to the app in the
last 24 hours. So there is a second way: send `KEY` from that phone to the
app's WhatsApp number. The reply always arrives, because the phone just wrote.

The button allows 3 tries per address and 10 tries in all, each hour, for
each key. A stranger who presses it only sends the key to its owner.

`ADMIN_PHONE` must not be the gate desk number. If it is, the admin key is
not sent, because guards must not get it. Set `ADMIN_PHONE` on Render.

## The admin page

The admin page at `/admin` lists every stored request, newest first, 50 at a
time. It asks for `ADMIN_KEY` once. The gate key never opens it, because every
guard holds the gate key. Without `ADMIN_KEY`, or when it is the same as
`GATE_KEY`, the admin page stays locked and the server log says why. The rest
of the app runs as usual.

1. The tiles count the requests by status. Tap a tile to show only that
   status. Waiting is pending and escalated together.
2. The search box finds a name, phone number, reference or person visited.
3. Tap a request to see the address, the guests, its two approvers, who
   decided (the approver, the backup, or the automatic approval), and every
   time: requested, sent to the backup, decided, entered, gate photo and exited.
4. The Show more button loads the next 50.
5. The table at the end lists the two approvers for each reason. Change opens
   both numbers for that reason. Both are required, with `+` and the country
   code, and they must differ. The change works at once, see "Approvers for
   each reason".

The page reads `GET /api/admin/visits` and `GET /api/admin/summary` with the
`X-Admin-Key` header. Neither returns the visitor's private token. Download
CSV gives the same log as the gate page.

## Approvers for each reason

Each reason on the form has a main approver and a backup approver. A request
goes to the main approver for its reason. After `ESCALATE_MINUTES` with no
answer, it goes to the backup for that reason. A reason the visitor types in
counts as the reason Other.

Only the two approvers of a reason can decide its requests. An approver who
sends YES or NO with the reference of another reason gets "goes to another
approver". An approver who sends anything else sees only the requests of their
own reasons.

The admin page sets each reason's two numbers. A saved pair is kept in the
database, so it stays when Render deploys again. From that moment, new requests go to
the new numbers, and the old numbers can no longer decide that reason's
requests, including requests already sent to them.

A reason with no saved pair uses the settings. Every reason uses
`MAIN_APPROVER` and `BACKUP_APPROVER` until `APPROVERS` changes it.
`APPROVERS` is JSON. It names only the reasons that differ:

```
APPROVERS={"Delivery": ["+919000000001", "+919000000002"], "Event": ["+919000000003", "+919000000004"]}
```

The reasons are `See a student`, `See an office`, `Delivery`, `Event` and
`Other`, the same list as `REASONS` in `config.py` and `static/app.js`. A name
that is not on the list stops the app at start, so a typo cannot send a reason
to the wrong person. Put each new number on the Meta recipient list too.

## How it works

1. The browser posts the form to `POST /api/requests`.
2. The server stores the request and gives it four things: a reference like
   `VR-4022` for the approvers, an entry code and an exit code like `KT-4821`
   for the gate, and a long private token for the browser.
3. The server sends one WhatsApp message to the main approver, as an approved
   template, see "The approval template".
4. The approver replies `YES VR-4022` or `NO VR-4022`.
5. Meta posts that reply to `POST /webhook/whatsapp`.
6. The server records the decision.
7. The visitor's page asks `GET /api/visit/<token>` every three seconds.
8. At the gate, the guard sends `IN` with the entry code on the visitor's pass,
   and then a photo of the visitor. The photo records the entry. Later, `OUT`
   with the exit code records the exit.

If no reply arrives within `ESCALATE_MINUTES`, the server sends the same details
to the backup approver. Escalation never decides anything.

## Automatic approval in working hours

A request made in working hours is approved automatically when no approver
answers within `AUTO_APPROVE_MINUTES`, 30 by default. Working hours are 10:00
to 17:00, Monday to Saturday, India time: 10:00 counts, 17:00 does not.
`WORK_HOURS`, `WORK_DAYS` and `WORK_TIMEZONE` change them.

- The server stores the approval time when the request is made. A request
  made outside working hours has none, and waits for a YES or a NO.
- A YES or a NO before that time wins. The automatic approval then does
  nothing.
- When it approves, both approvers get a WhatsApp message. It is plain text,
  so an approver who has not written in 24 hours may not get it.
- The admin page and the CSV show `auto` in "decided by".
- The visitor never sees the approval time or who approved.
- While Render sleeps, the timer does not run. If the server is asleep at the
  approval time, the request is approved when the server next wakes, for
  example when the visitor or the guard opens a page.

Set `AUTO_APPROVE_MINUTES=0` to turn this off.

## Entry and exit codes

Each pass has two codes, and each code does only its own job.

1. Once the request is approved, the visitor's pass shows the entry code. The
   entry code records the entry and nothing else.
2. When the guard records the entry, the pass shows the exit code instead. The
   exit code records the exit and nothing else.
3. The reference, such as `VR-4022`, is for the approvers. At the gate it shows
   who the visitor is, but it records nothing.

A code is two letters and four digits, such as `KT-4821`. The letters leave out
I and O, which look like 1 and 0, and they are never VR, so a code never looks
like a reference. The server picks each code with the Python `secrets` module,
so one code tells nothing about the next. There are about 5.7 million codes.
The guard can type `kt4821` or `KT 4821`.

No message, list or export shows a gate code. Only the visitor's own page shows
one, and only the code for the next step. A WhatsApp reply repeats a code only
when the sender typed that code.

The visitor's page must load once after the entry to show the exit code. It
asks the server every three seconds, so this needs a connection for a moment
while the visitor is inside.

## The life of a pass

Each arrow happens once and cannot be undone.

```
pending ──(no reply in time)──> escalated
   │                                │
   └──(YES / NO, or auto-approval)──┘
                 │
        approved │ declined
                 │
   (guard sends IN and the entry code, then a photo)
                 │
              inside
                 │
   (guard records exit with the exit code)
                 │
              closed
```

A closed pass is dead. Neither code works on it again, and it stops showing
the visitor. The visitor app drops the pass and forgets the codes. The gate page and
the WhatsApp lookup answer with the entry and exit times and nothing personal.
The privacy screen promises the gate desk sees the details while the visit is
open, so a finished visit has to stop answering. The CSV export still holds the
whole log for whoever runs the campus.

## WhatsApp commands

One phone number can be the approver, the backup approver and the guard at the
same time, so each job has its own word.

| You send      | What happens                                                |
|---------------|-------------------------------------------------------------|
| `VR-4022`     | Shows the pass by its reference                             |
| `KT-4821`     | Shows the pass and says what you can do next with that code |
| `YES VR-4022` | Approves the request                                        |
| `NO VR-4022`  | Declines the request                                        |
| `IN KT-4821`  | With the entry code: asks for a photo of the named visitor  |
| a photo       | Records the entry for the last `IN`                         |
| `OUT RM-0937` | With the exit code: records the exit                        |
| `KEY`         | From `GUARD` or `ADMIN_PHONE`: sends back that number's key |
| anything else | Sends back the request that is waiting, with full details   |

`YES` and `NO` work without a reference when exactly one request is waiting. The
server ignores every number that is not an approver, `GUARD` or `ADMIN_PHONE`.

### The photo at the gate

On WhatsApp, `IN` alone lets nobody in. The server answers "Take a photo of
Asha Rao and send it here." The guard takes the photo in the same chat and
sends it. That photo records the entry, and the server answers with the pass.

- The photo must come within 10 minutes of the `IN`. After that, send `IN`
  again. `PHOTO_MINUTES` in `app.py` sets this time.
- Each `IN` replaces the one before it. If you send `IN KT-4821` and then
  `IN PB-5100`, the photo lets in the visitor of PB-5100, and the reply names
  that visitor.
- One photo lets in one person. A second photo on the same `IN` does nothing.
- Only the `GUARD` number can send the photo. A photo from any other number
  changes nothing.

The photo itself stays in the gate desk's WhatsApp chat. The server keeps
WhatsApp's id for the photo and the time it arrived. The visit log shows that
time in the `photo_at` column. The privacy screen in the visitor app says the
same thing, so change both together.

## Two kinds of address, on purpose

The reference has only 9,000 possibilities, so it is not a secret. Anyone could
guess one. It therefore never opens anything on its own, and at the gate it
records nothing at all.

- The visitor's browser reads `GET /api/visit/<token>`. The token is 22
  characters of random text, so nobody can guess another visitor's request.
- The gate reads `/api/pass/<code or reference>` and records with
  `/api/pass/<entry or exit code>/<entry or exit>`. Every one of those calls
  needs the `X-Gate-Key` header. The guard types that key once on the gate page.

## The visit log

Every request keeps its own row, including the exact times it was approved, the
visitor entered, and the visitor left. The gate page has a **Download log**
button that saves the whole history as a CSV file, and the same data is at
`GET /api/export.csv` with the `X-Gate-Key` header.

The CSV has one row per visit and these columns:

```
reference, name, phone, address, reason, visiting, guests,
status, created_at, escalated_at, decided_at, entered_at, exited_at, photo_at
```

Times are UTC in ISO format. A visit that never entered has empty `entered_at`
and `exited_at`, so you can filter completed visits on those columns. An entry
recorded on the gate page has an empty `photo_at`, because the page takes no
photo.

A cell that opens with `=`, `+`, `-` or `@` is written with a leading quote.
Excel and Sheets run such a cell as a formula, so a visitor who types
`=HYPERLINK(...)` as their name would otherwise have it executed on whoever
opens the log. The text is kept, only disarmed.

Records are deleted `RETAIN_DAYS` after they are created, 90 days by default.
The privacy screen in the visitor app states that same number, so the promise and
the code agree. Change one and change the other.

## How the work grows

In this section, n is the number of stored visits, and k is the number of rows
that an operation returns or changes. An index is a sorted copy of some columns
that Postgres can search without reading every row.

| Work                                | Cost            | How                                          |
|-------------------------------------|-----------------|----------------------------------------------|
| Visitor status check, every 3 s     | O(log n)        | One query: the token index, codes joined     |
| Look up a pass by its code          | O(log n)        | One query: the code key, visit joined        |
| Decide, enter, exit                 | O(log n)        | One UPDATE that returns the new row          |
| Escalation check, every 30 seconds  | O(log n + k)    | Index on status and created time             |
| Gate board, every 30 seconds        | O(log n + k)    | Index on status and decision time            |
| Purge, every 30 seconds             | O(log n + k)    | Reads only expired visits and their photos   |
| One admin page, first or fiftieth   | O(log n + 50)   | Starts after the last row of the page before |
| Admin counts by status              | O(n)            | One pass over an index, not the table        |
| Admin search                        | O(n) at worst   | Reads rows until the page is full            |
| CSV export                          | O(n)            | It returns every row                         |
| Rate limit, per request             | O(1) on average | Old times fall off the front of a queue      |

A reference has four digits, so there are 9000 references. A new reference is
picked at random and tried up to 20 times. When most references are in use, for
example 8000 visits kept for 90 days, a request can fail to find a free one.
Keep `RETAIN_DAYS` times the visits per day well under 9000. The gate codes have
about 5.7 million values, so they do not run short.

Admin search is the one request that can read every row. A trigram index
would fix that, but the test database has no `pg_trgm`, and the tests and
production must use the same schema. The retention period keeps n small, so
the scan stays fast.

On a slow connection, the number of round trips costs far more than any of
these. The app and its database both run in Singapore, the nearest region to
India, so each trip is short. A lookup took 0.14 s from India there, against
0.33 s from Oregon. Each request above still makes one database query, and
the pages save trips as described in "On a weak signal".

## On a weak signal

The visitor's page is built for a phone at the gate with little or no signal.

- The phone keeps a copy of the last pass it saw. The page draws it at once,
  before any answer from the server, and says when it was last updated. A
  lost connection never deletes the pass. Only an unknown or closed pass, or
  a new request, does. The copy holds no phone number or address.
- A service worker, `static/sw.js`, keeps the page and its script on the
  phone. The page opens with no signal, and it opens at once while the free
  server wakes up. API calls always go to the network.
- At start, the page asks for its settings and its pass at the same time.
- The status check pauses while the page is hidden. It runs at once when the
  page shows again or the phone comes back online. After failures, it waits
  longer each time, up to 30 seconds.
- Each script's address carries a hash of its content, such as
  `app.js?v=1a2b3c4d5e`. The browser keeps each version for a year. The pages
  are checked on every load and answer 304 when unchanged.
- Render compresses every answer with Brotli.

On the server, two pooled connections stay open. A request waits at most 5
seconds for a connection. A read whose connection breaks under it runs once
more. An insert or update never does, because its COMMIT can land even when
the reply is lost. At start, the app tries the database again after 1, 2, 4
and 8 seconds, because Neon takes a moment to wake.

## Files

| File                                   | What it holds                                                 |
|----------------------------------------|---------------------------------------------------------------|
| `USER_MANUAL.md`                       | Setup, daily use and upkeep, for the people who run the app   |
| `app.py`                               | Flask routes, the escalation timer and the delete timer       |
| `db.py`                                | Postgres storage, and the migrations that build its tables    |
| `testdb.py`                            | Starts a throwaway Postgres for the two test files            |
| `whatsapp.py`                          | Meta API send, message text, command reading                  |
| `config.py`                            | Settings read from the environment                            |
| `check_setup.py`                       | Checks your settings and sends one test message               |
| `test_app.py`                          | Runs the whole flow with WhatsApp stubbed out                 |
| `test_concurrency.py`                  | Hammers the app from many threads to check the races          |
| `test_form.js`                         | Checks the web pages in a real DOM. Needs `npm install jsdom` |
| `ruff.toml`, `eslint.config.mjs`       | Linter settings, and why two rules are off                    |
| `static/index.html`, `static/app.js`   | The visitor app                                               |
| `static/gate.html`, `static/gate.js`   | The gate desk page                                            |
| `static/admin.html`, `static/admin.js` | The admin page with every request                             |
| `static/shared.js`                     | The CSV download and the forgot-key call, for gate and admin  |
| `render.yaml`                          | The Render settings: region, commands and setting names       |
| `gunicorn.conf.py`                     | Starts and stops the database and timer in the worker         |
| `static/sw.js`                         | Keeps the visitor page on the phone, so it opens offline      |

## Settings

| Name                   | What it is                                               |
|------------------------|----------------------------------------------------------|
| `META_TOKEN`           | Access token from the WhatsApp API Setup page            |
| `META_PHONE_NUMBER_ID` | Phone number ID from the same page                       |
| `META_VERIFY_TOKEN`    | Any text. Type the same text into the Meta webhook page  |
| `META_APP_SECRET`      | App secret. Leave empty to skip the signature check      |
| `MAIN_APPROVER`        | Approver number, like `+911234567890`                    |
| `BACKUP_APPROVER`      | Backup approver. Defaults to the main approver           |
| `APPROVERS`            | Optional JSON: other approvers for some reasons          |
| `GUARD`                | Gate desk number. Defaults to the main approver          |
| `ADMIN_PHONE`          | Gets the admin key on request. Defaults to main approver |
| `GATE_KEY`             | Password for the gate page. Keep it off the internet     |
| `ADMIN_KEY`            | Password for the admin page. Must differ from `GATE_KEY` |
| `DATABASE_URL`         | Postgres connection string from Neon. Keep it secret     |
| `GATE_DESK_PHONE`      | Number shown on the "Call gate desk" button              |
| `ESCALATE_MINUTES`     | Minutes before the backup approver is asked. Default 15  |
| `AUTO_APPROVE_MINUTES` | Minutes before auto-approval in work hours. 0 = off      |
| `WORK_HOURS`           | Working hours, whole hours. Default `10-17`              |
| `WORK_DAYS`            | Working days. Default `Mon,Tue,Wed,Thu,Fri,Sat`          |
| `WORK_TIMEZONE`        | Clock for working hours. Default `Asia/Kolkata`          |
| `RETAIN_DAYS`          | Days a record is kept before deletion. Default 90        |
| `REQUESTS_PER_HOUR`    | New requests allowed per address per hour. Default 60    |
| `BEHIND_PROXY`         | Set to `true` on Render. Leave unset on your own machine |
| `REQUEST_TEMPLATE`     | Approval request template. Default `visit_request`       |
| `TEMPLATE_LANGUAGE`    | Language code of that template. Default `en`             |
| `TEMPLATE_FALLBACK`    | `true`: plain text when the template fails. Default off  |

Write every phone number in E.164 form: a plus sign, the country code, then the
number. Each approver number must also be on the recipient list in the Meta API
Setup page, because a test number only sends to numbers on that list.

### The approval template

WhatsApp delivers plain text only to a person who messaged your business
number in the last 24 hours. Outside that window, Meta accepts the message,
answers 200, and then drops it. The app sees no error, and the approver gets
nothing. An approver who has not used the number since yesterday is outside
the window.

The approval request therefore goes out as the template `visit_request`, which
WhatsApp delivers at any time. The template has category Utility, language
`en`, and this body:

```
Campus visit request {{1}}.
{{2}}

Name: {{3}}
Phone: {{4}}
Address: {{5}}
Reason: {{6}}
Visiting: {{7}}
With: {{8}}

Reply YES or NO followed by the reference to decide this request.
```

`{{1}}` is the reference, `{{2}}` says whether this is a new request or an
escalation, and the rest are the visitor's details. Replies to the approver's
and the guard's own commands stay plain text, because the person just wrote
to the number.

Meta must approve the template before it works. What happens when Meta
refuses it depends on `TEMPLATE_FALLBACK`:

- Unset, the default: the visitor sees "Could not reach the approver" and can
  try again. An escalation that fails is logged and tried again 30 seconds
  later. Use this in production.
- `true`: the app sends plain text instead and writes `Approval template
  refused` to the log. Use this only while Meta reviews a new template.

Leave the fallback off in production. Meta can pause or disable a template,
for example after low quality ratings. With the fallback on, every request
would then go out as plain text. Plain text is lost for any approver who has
not written to the number in 24 hours, and the visitor is still told that the
request went out. With the fallback off, the failure reaches the visitor.

If you turn the fallback on during a review, set `TEMPLATE_FALLBACK=true` in
the Render Environment page, and delete it there once the template shows
Approved in WhatsApp Manager.

If you make a new Meta app or WhatsApp account, create the template again in
WhatsApp Manager, under Message templates, with the same name and body.

Meta reports a lost message later, through the same webhook. The app writes
each one to the log as `WhatsApp could not deliver to <number>: error <code>`.
Error 131047 means the 24-hour window.

## The database

The visits live in a Postgres database on Neon (https://neon.tech). The app
reads its address from `DATABASE_URL`. In the Neon console, open the project,
click Connect, and copy the connection string. The string holds the database
password, so put it only in `.env` and in the Render Environment page.

On your own machine, use a separate Neon branch, so a test visit never lands
in the live list. A branch is a copy of the database that you can change on
its own. Make one in the Neon console under Branches.

The app builds its tables itself when it starts. `db.py` holds a list of
migrations, which are the schema changes in order. The table
`schema_migrations` records the steps that this database already ran, and
each start runs only the new ones. To change the schema:

1. Add a new step at the end of `MIGRATIONS` in `db.py`.
2. Only add things in that step: a new table, or a new column that is
   nullable or has a default. While Render deploys a new version, the old
   version keeps running for a moment, and it must not break on the new schema.
3. Never edit or remove a step after you deploy it. A database that already
   ran it never runs the new text.
4. Run the checks, then deploy. The visits stay.

To remove a column, stop using it in one version, and drop it in a later step.

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
page, with your `META_VERIFY_TOKEN`, and press Verify and save. Then subscribe the
**messages** field. The app receives nothing until you do that.
It is the step people miss.

## Put it on the internet with Render

1. Push this folder to GitHub. `.env` stays out, see `.gitignore`.
2. On https://render.com, choose New, then Web Service, and pick the repository.
   Pick the region nearest the campus, and put the Neon database in the same
   region. For a campus in India, that is Singapore.
3. Use the build and start commands from `render.yaml`. Render reads that
   file by itself only for a service made from a Blueprint.
4. Fill in every setting from the table above in the Environment section.
5. Deploy. Render gives you an address like
   `https://visitor-access-sg.onrender.com`.
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
- The free plan has no disk, so the visits live in Neon, not on Render. They
  stay when you deploy again. Records still delete themselves after `RETAIN_DAYS`.
- The Neon free plan gives 100 compute hours a month, which is about 13 hours
  a day awake. The app checks for escalations every 30 seconds, so Neon stays
  awake while Render is awake. Both sleep after a quiet spell.

## Demo run

1. Open your address and send a request.
2. Read the WhatsApp message on your phone.
3. Reply `YES VR-4022`, using the reference from the message.
4. Watch the page turn green and show the entry pass with its entry code.
5. Send `IN` and the entry code on WhatsApp, for example `IN KT-4821`. The reply
   asks for a photo.
6. Take a photo in the same chat and send it. You can also use `/gate` in a
   browser instead of steps 5 and 6.
7. The visitor page changes to "Inside campus" by itself, and the pass now
   shows the exit code.
8. Send `OUT` and the exit code. The visitor page says "Visit complete".
9. Send the exit code once more. It says the pass is closed.

To show a decline, reply `NO` with the reference.

To show escalation, set `ESCALATE_MINUTES=1` and restart. Send a request and do
not reply. After one minute the backup approver gets the same details.

## When something fails

- Error 190: the access token expired. Use a permanent token, see above.
- Error 131030: the number is not on the Meta recipient list. Add it.
- The visitor sees the request as sent, but the approver gets nothing: search
  the Render log for `could not deliver`. Error 131047 means the 24-hour
  window, see "The approval template". `Approval template refused` means the
  template is missing or still waiting for Meta's review.
- Error 132001: the template does not exist, or Meta has not approved it yet.
- The reply never changes the page: the webhook address does not match your
  current address, or the **messages** field is not subscribed.
- The webhook returns 403: `META_APP_SECRET` does not match the app.
- The gate page says "Wrong gate key": press "Forgot gate key?", or send `KEY`
  from the gate desk phone, then type the key again.

## Checks

The checks start their own empty Postgres from the `pgserver` package, so
they never touch Neon. Install it once.

```
.venv\Scripts\python.exe -m pip install pgserver
```

```
.venv\Scripts\python.exe test_app.py
```

```
.venv\Scripts\python.exe test_concurrency.py
```

The first runs the whole flow without sending any WhatsApp message: approval,
decline, escalation, repeated deliveries, the code-guessing defense, the entry
and exit codes and where they may appear, the admin key, both gate routes, the photo at the gate, the export, the delete-after-retention rule, and the
migrations.

The second proves the app survives load: sixty visitors submitting at the same
instant all get unique codes, and twenty guards pressing Record entry on the same
visitor produce exactly one entry, not twenty.

The third checks the two web pages. It loads them in a real DOM, so it tests
what the visitor sees rather than what the server returns. It needs jsdom, which
the app itself does not use.

```
npm install jsdom
node test_form.js
```

It covers the three rules the pages have to keep: Continue and Review refuse a
half filled form and turn each wrong field light red, a field takes one line of
plain text and nothing else, and a closed pass stops showing the visitor. It
also checks the "+" button that adds a person: the name box opens only after
you press "+", and a name left in the box still counts when you press Review.

Two linters are set up, and both report nothing on a clean tree.

```
ruff check .
npx eslint static test_form.js
```

`ruff.toml` and `eslint.config.mjs` each turn off a small number of rules and
say why in a comment. The important one is `no-implicit-globals`. The pages
have no build step, so a button calls its handler straight from an `onclick`
attribute, and an attribute can only reach a global name. Wrapping the script
in an IIFE would satisfy the rule and break both pages.

## Limits and who they protect

Both limits count per address, per hour.

`REQUESTS_PER_HOUR` stops a stranger who finds the public address from making
the approver's phone ring all night. People on one campus Wi-Fi share a single
address, so the default of 60 is set for a whole group rather than one person.
Raise it if a class tests at once.

There is deliberately no lockout on the gate key. A correct key always works.
The key is long random text, so guessing it is not a real threat, while a
lockout is: everyone at one gate shares one address, so a single person
mistyping would shut out the whole gate for an hour.

`BEHIND_PROXY` must be set to `true` on Render, and it is easy to miss.
Render applies environment changes in `render.yaml` only on a blueprint sync,
not on an ordinary deploy, so check the service's own Environment page after
adding one. Without it every visitor is counted as the same caller, because
the address the server sees is Render's proxy rather than the person.

`BEHIND_PROXY` decides where the caller's address is read from. On Render a
proxy sits in front and appends the true address to `X-Forwarded-For`, so the
server reads the last entry. On your own machine nothing sets that header, and
trusting it would let anyone invent an address and get a fresh allowance on
every request. Set it to `true` only when a proxy really is in front.

## Known limits

- The gate key is one shared password. Every guard uses the same one, and there
  is no record of which guard pressed the button. It also unlocks the full export,
  so anyone with the key can download every visitor's name, phone and address.
  A guard types it once per device. The page asks for it before it shows anything
  else, because a code without a key can do nothing. The admin page has its
  own key, so a guard cannot open it.
- Only WhatsApp asks for a photo. The **Record entry** button on the gate page
  still lets a visitor in without one. Use WhatsApp at the gate if every entry
  must have a photo.
- The approver is one fixed number. A real deployment would look up the student
  being visited and message that person.
- The 4-digit reference is short enough to guess, which is why it never works on
  its own and records nothing at the gate. Do not make it do more than it does
  here.
- A visitor's browser holds the only link to their request. Clear the browser
  data, or switch phone, and they cannot reach it again, because the reference
  deliberately retrieves nothing. They must send a new request. This is the
  price of not letting anyone read a stranger's details by guessing a reference.
- Records live in a file on the server. On a free host with no disk, a fresh build
  wipes them. Download the CSV before redeploying if the log matters.

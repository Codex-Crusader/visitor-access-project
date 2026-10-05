# Maintenance

This document tells each person how to use the app every day. It also tells
the person who runs the app how to change, deploy, watch and repair it. To set up a
new copy, read [setup.md](setup.md). For security and privacy, read
[safety.md](safety.md).

## Who does what

| Role     | Uses                       | Job                                       |
|----------|----------------------------|-------------------------------------------|
| Visitor  | The web page on a phone    | Asks to come in, and shows the pass       |
| Approver | WhatsApp                   | Says yes or no to each request            |
| Guard    | The gate page, or WhatsApp | Records each entry and exit               |
| Admin    | The admin page             | Reads every request and downloads the log |

## Visitor

1. Open `<address>` on your phone.
2. Tap Request a Visit.
3. Fill in your name, phone number and address, then tap Continue.
4. Pick the reason for the visit, and type the person you visit. Add the
   people who come with you. Tap Review.
5. Read the details, then tap Send request. Keep the page open.
6. Wait for the decision. The page shows it a few seconds after the reply.
7. If the request is approved, tap Open pass, and show the entry code to the
   guard.
8. After the guard lets you in, the pass shows a different code, the exit
   code. Show it to the guard when you leave.

After the exit, the pass closes and both codes stop working. If the page says
that the request was declined, do not go to the gate. Use the Call gate desk
button for help.

A pass works for 48 hours after you send the request. The pass shows the
time it ends. After that time, the code does not open the gate, and you must
send a new request. If you are already inside, you can still leave.

Your phone keeps a copy of your pass. If the signal at the gate is weak or
gone, open the page anyway. It shows the pass from the copy and says when it
was last updated. It updates by itself when the signal comes back.

## Approver

You get a WhatsApp message with the visitor's details and a reference such as
`VR-4022`.

1. To approve, reply `YES VR-4022`.
2. To decline, reply `NO VR-4022`.

If only one request waits for you, `YES` or `NO` alone is enough. If the
reference has a typing mistake, the app answers "No request has reference"
and decides nothing. Send any other message to see the requests that wait
for you.

If you do not answer in 15 minutes, the backup approver gets the same
request. The first reply decides. A reply after that changes nothing.

If the request was made between 10:00 and 17:00, Monday to Saturday, and no
one answers in 30 minutes, the app approves it. Both approvers get a message
that says so. To stop a visitor, reply `NO` before that time.

A request that nobody approves in 48 hours expires. A reply after that gets
"expired", and the visitor must send a new request.

## Guard

You can work from the gate page or from WhatsApp. Both record the same thing.

### On the gate page

1. Open `<address>/gate`.
2. Type the gate key. The page asks for it once on each phone. If you do not
   know it, tap "Forgot gate key?". The app sends the key to the gate desk
   WhatsApp. If it does not arrive, send `KEY` from the gate desk phone to the
   app's WhatsApp number.
3. Type the code on the visitor's pass, and tap Check pass. Small letters and
   spaces are correct, for example `kt 4821`.
4. If the pass is approved, tap Record entry.
5. When the visitor leaves, type the exit code, tap Check pass, then tap
   Record exit.
6. Tap Next visitor to clear the screen.

The page shows two lists:

1. Inside now: everyone on campus, the longest first. A yellow row means that
   the visitor entered more than 8 hours ago.
2. Expected: the approved passes that nobody has used yet and that have not
   expired.

A tap on a name only shows the details. It records nothing. The lists refresh
every 30 seconds and after each entry or exit. The badge says Live while the
lists are fresh and Offline after a refresh fails. Download log saves every
visit as a CSV file.

### On WhatsApp

1. Send `IN` and the entry code, for example `IN KT-4821`.
2. The app asks for a photo of the visitor. Take it in the same chat and send
   it in 10 minutes or less. The photo records the entry.
3. When the visitor leaves, send `OUT` and the exit code, for example
   `OUT RM-0937`.

To look at a pass and record nothing, send only the code or the reference.

The rules for the photo:

1. If the photo comes more than 10 minutes after `IN`, send `IN` again.
2. Each `IN` replaces the one before it. The photo lets in the visitor of the
   last `IN`, and the reply names that visitor.
3. One photo lets in one person. A second photo on the same `IN` does nothing.
4. Only the `GUARD` number can send the photo.

Only WhatsApp asks for a photo. The Record entry button on the gate page lets
a visitor in without one. If every entry must have a photo, use WhatsApp.

### When the gate says no

| The gate says          | Do this                                     |
|------------------------|---------------------------------------------|
| Not approved yet       | Do not let the visitor in. Ask them to wait |
| Declined               | Do not let the visitor in                   |
| Pass expired           | Do not let them in. Ask for a new request   |
| ... is the exit code   | Ask for the entry code                      |
| This pass is closed    | The visit is over. The code is dead         |
| Wrong gate key         | Tap "Forgot gate key?", then type the key   |

## Admin

1. Open `<address>/admin`.
2. Type the admin key. It is different from the gate key. If you do not know
   it, tap "Forgot admin key?". The app sends the key to `ADMIN_PHONE` on
   WhatsApp. If it does not arrive, send `KEY` from that phone to the app's
   WhatsApp number.
3. The page has two tabs: Visits and Approver numbers. Visits opens first.
4. On the Visits tab, tap a tile to show only the requests with that status.
   Waiting means pending or with the backup approver.
5. Use the search box to find a name, phone number, reference or the person
   visited.
6. Read the line under each name. It shows the decision and who made it, for
   example "Declined by the backup approver +919876543211". A decision made
   before 5 October 2026 shows no number, and the oldest show no role,
   because the app did not keep them then.
7. Tap a request to see all its details and times, and when its pass ends.
8. Show more loads the next 50 requests.
9. Use Download CSV to save the whole log.

### Change the approvers

1. Tap the Approver numbers tab.
2. Tap Change on the reason.
3. Type the approver's number and the backup's number. Write each one with
   `+` and the country code, like `+919876543210`. Both are required, and
   they must be different.
4. Tap Save both numbers.

The change works at once. New requests go to the new numbers. The old numbers
can no longer decide that reason's requests, also the requests already sent
to them. While the app uses Meta's test number, also add each new number to
the recipient list in Meta's API Setup page.

## WhatsApp commands

One phone number can be an approver and the guard at the same time, so each
job has its own word.

| You send      | What happens                                                |
|---------------|-------------------------------------------------------------|
| `VR-4022`     | Shows the pass by its reference                             |
| `KT-4821`     | Shows the pass and the next step for that code              |
| `YES VR-4022` | Approves the request                                        |
| `NO VR-4022`  | Declines the request                                        |
| `IN KT-4821`  | With the entry code: asks for a photo of the visitor        |
| a photo       | Records the entry for the last `IN`                         |
| `OUT RM-0937` | With the exit code: records the exit                        |
| `KEY`         | From `GUARD` or `ADMIN_PHONE`: sends back that number's key |
| anything else | Sends back the requests that wait for you                   |

A reference can also be typed as `VR4022`, `VR 4022` or `4022`. The app
ignores every number that is not an approver, `GUARD` or `ADMIN_PHONE`.

## Forgotten keys

The gate page and the admin page each have a "Forgot ... key?" button. It
sends the key by WhatsApp to one fixed number: the gate key to `GUARD`, and
the admin key to `ADMIN_PHONE`. The page shows only the last four digits of
that number, never the key.

WhatsApp delivers this message only if that number wrote to the app in the
last 24 hours. If it does not arrive, send `KEY` from that phone to the app's
WhatsApp number. The reply always arrives, because the phone just wrote.

The button allows 3 tries from one address and 10 tries in total, each hour,
for each key.

## Change a key

Use long random keys. A short key is easy to guess.

1. Open the service on Render, then Environment.
2. Change `GATE_KEY`, `ADMIN_KEY`, or both. The two keys must be different.
3. Click Save, rebuild, and deploy.
4. Give the new gate key to each guard. Each gate page asks for it once.

## Change the address

If the app moves and its address changes, do these steps:

1. Give the new address to visitors, guards and admins.
2. Change the Callback URL on the Meta Configuration page, as in step 5 of
   [setup.md](setup.md). If you do not, the app stops receiving replies.
3. Change the repository variable `HEALTH_URL`, see "The uptime check".

## Ship a change

1. Run the checks on your own machine, see "The checks".
2. Push to GitHub. The workflow Tests runs every check again on Python 3.11
   and 3.14. Open the Actions tab and wait for a green result.
3. If the result is red, do not deploy. Open the run to read which check
   failed.
4. Deploy on Render. A service made by hand from a public repository URL does
   not deploy by itself. Open the service, click Manual Deploy, then Deploy
   latest commit.
5. Make sure that the new version is live. Open a page or a script that
   changed, because the old and the new version give the same status code.
6. Read the Render log for a minute after the start. The first background
   round runs at once, and its errors show there.

### Database changes

The app builds and changes its tables by itself when it starts. `db.py` holds
the list `MIGRATIONS`, which is the schema changes in order. The table
`schema_migrations` records the steps that this database already ran, and
each start runs only the new steps.

1. Add a new step at the end of `MIGRATIONS`.
2. Only add things in that step: a new table, or a new column that is
   nullable or has a default. While Render deploys, the old version runs for
   a moment against the new schema, and it must not break.
3. Never edit or remove a step after you deploy it. A database that already
   ran it never runs the new text.

To remove a column, stop using it in one version, and drop it in a later
step.

### Roll back

Render can deploy an older version from the Deploys page with Rollback. Do
not roll back to a version from before 5 October 2026 (commit `ecf09e0`).
Those versions do not know the status `expired`. The gate and WhatsApp then
fail on every expired pass.

## The checks

The tests start their own empty Postgres from the `pgserver` package, so they
never touch Neon. Install it once.

```
.venv\Scripts\python.exe -m pip install pgserver
```

Then run each check. Each one must finish with no error. The tests and
ruff end with "passed", and eslint prints nothing when the code is clean.

```
.venv\Scripts\python.exe test_app.py
.venv\Scripts\python.exe test_concurrency.py
npm install
node test_form.js
ruff check .
npx eslint static test_form.js
```

1. `test_app.py` runs the whole flow with WhatsApp stubbed out. It sends no
   message.
2. `test_concurrency.py` makes many requests and many guards at the same
   moment, and checks that each code is unique and each entry happens once.
3. `test_form.js` loads the three pages in a real DOM with jsdom.
4. `ruff` and `eslint` are the linters. Their settings files say why each
   rule that is off is off. The important one is `no-implicit-globals`. The
   pages have no build step, so each button calls a global function from an
   `onclick` attribute.

To use another Postgres for the tests, set `TEST_DATABASE_URL`. The tests
write and delete rows, so never point it at the live database.

## The uptime check

The workflow Uptime opens `<address>/api/health` every hour from 08:30 to
18:30 India time. The health address answers 200 when the database answers
and Meta accepts the token. It answers 503 and names the part that failed,
for example `{"database":true,"whatsapp":false}`.

A failed run sends an email. These facts come from GitHub's documentation:

1. The email goes to the GitHub user who last changed the `cron` line in
   `.github/workflows/uptime.yml`. To get the emails yourself, change that
   line in a commit of your own.
2. In a public repository, GitHub turns off scheduled workflows after 60 days
   with no activity in the repository. Push a commit, or click Enable
   workflow on the Actions tab, before that happens.
3. A scheduled run can start late when GitHub is busy, and GitHub can drop
   it.

Before the first run, set the address as a repository variable. On GitHub,
open Settings, then Secrets and variables, then Actions, then Variables, and
add `HEALTH_URL` with the value `<address>`. The address is not in the file,
because the repository is public.

To test the check, open the Actions tab, click Uptime, then Run workflow. To
see a failure, type a wrong address in the box.

Each run wakes the free server, which then stays awake for about 15
minutes. In working hours, that uses about a quarter of each hour of Render
time and a few minutes of Neon time. Both stay well inside the free plans.

The meaning of a failed run:

1. `"database":false`: Neon does not answer. Open the Neon console. Look at
   the compute hours and the storage, and make sure that `DATABASE_URL` is
   correct.
2. `"whatsapp":false`: Meta refuses the token. Make a new permanent token, as
   in step 1 of [setup.md](setup.md), and put it in `META_TOKEN`. The app
   asks Meta at most once an hour, so the result can be one hour old.
3. A timeout or a 404: the server does not run, or the address changed.

## Where the data lives

The visits live in the Neon database. They stay when Render deploys a new
version. The app deletes each visit `RETAIN_DAYS` after the request, 90 days
by default, as the privacy screen promises.

The CSV from Download log is the only copy that you control. Download it
before a large change, and on a fixed day each week. Neon can restore the
database to an earlier time, under Backup & Restore in the Neon console. On
the free plan, that window is only 6 hours (the project's "History
retention"). A mistake found the next day cannot be undone there.

The CSV has one row for each visit, with these columns:

```
reference, name, phone, address, reason, visiting, guests, status,
created_at, escalated_at, decided_at, decided_by, entered_at, exited_at, photo_at
```

Times are UTC. A visit that never entered has empty `entered_at` and
`exited_at`. An entry recorded on the gate page has an empty `photo_at`.

## The free plans

1. Render sleeps after 15 quiet minutes. The first request after that waits
   up to about a minute. The visitor's page still opens at once from the
   phone's copy.
2. While Render sleeps, the timer does not run. Reminders to the backup
   approver, automatic approvals and expiries wait until the app wakes. The
   app wakes when somebody opens a page or sends a WhatsApp message.
3. Neon gives 100 compute hours a month and 0.5 GB. The timer asks the
   database only when a reminder, an approval or an expiry is due, and once
   an hour when nothing is due. Neon can sleep in between. An open visitor
   page asks every 3 seconds and an open gate page every 30 seconds, so Neon
   stays awake while people use the app.
4. If the compute hours run out, the app stops until the next month, and the
   uptime check reports `"database":false`.

## How the app behaves

### The background timer

The timer runs inside the server. Each round does four jobs. It approves the
requests that are due for automatic approval, and it asks the backup approver
about the requests that nobody answered. Then it marks old passes as expired
and deletes old records. After the round, it sleeps until the next job is due. It sleeps 30 seconds at least, so a
failed WhatsApp message is tried again soon, and one hour at most. A new
request wakes it early. The first round runs at once when the server starts,
so work that became due while the server slept is done on wake.

### On a weak signal

1. The phone keeps a copy of the last pass it saw. The page draws it at once,
   before any answer from the server, and says when it was last updated. The
   copy holds no phone number and no address.
2. A service worker, `static/sw.js`, keeps the visitor page and its script on
   the phone. The page opens with no signal.
3. The status check stops while the page is hidden. It runs again when the
   page shows, or when the phone comes back online. After failures, it waits
   longer each time, up to 30 seconds.
4. Each script's address holds a hash of its content, so the browser keeps
   each version for a year. The pages are checked on each load.
5. The gate page needs a signal to check a pass. With no signal, the guard
   cannot check any pass, on the page or on WhatsApp.

### Fixed times in the code

| Name            | File             | Value | What it sets                               |
|-----------------|------------------|-------|--------------------------------------------|
| `PHOTO_MINUTES` | `app.py`         | 10    | Minutes the guard has to send the photo    |
| `LONG_HOURS`    | `static/gate.js` | 8     | Hours inside before the row turns yellow   |
| `IDLE_SECONDS`  | `app.py`         | 3600  | The longest sleep of the background timer  |

### The database connections

On the server, two database connections stay open. A request waits 5 seconds
at most for a connection. A read whose connection breaks runs once more. A
write never runs twice, because its COMMIT can land when the reply is lost.

### How the work grows

In this table, n is the number of stored visits. k is the number of rows
that an operation returns or changes.

| Work                              | Cost            | How                                         |
|-----------------------------------|-----------------|---------------------------------------------|
| Visitor status check, every 3 s   | O(log n)        | One query on the token index                |
| Look up a pass by its code        | O(log n)        | One query on the code key                   |
| Decide, enter, exit               | O(log n)        | One UPDATE that returns the new row         |
| Background round, when work is due| O(log n + k)    | Indexes on status and time                  |
| Gate board, every 30 s            | O(log n + k)    | Index on status and request time            |
| One admin page, first or fiftieth | O(log n + 50)   | Starts after the last row of the last page  |
| Admin counts by status            | O(n)            | One pass over an index                      |
| Admin search                      | O(n) at worst   | Reads rows until the page is full           |
| CSV export                        | O(n)            | It returns every row                        |

A reference has four digits, so there are 9,000 references. Keep
`RETAIN_DAYS` multiplied by the visits in one day well under 9,000, or a new
request can fail to find a free reference. Admin search reads every row when
the word is rare. A trigram index (`pg_trgm`) can fix that, but the test
database does not have it, and the tests must use the same schema as
production. The retention period keeps n small, so the search stays fast.

## When something fails

| You see                                             | Do this                                                 |
|-----------------------------------------------------|---------------------------------------------------------|
| Error 190 in the log                                | The Meta token expired. Make a new permanent token      |
| Error 131030                                        | The number is not on the Meta recipient list. Add it    |
| Error 132001                                        | The template does not exist or is not approved yet      |
| `could not deliver` with error 131047               | The 24-hour window. Make sure the template is in use    |
| `Approval template refused`                         | The template is missing or waits for Meta's review      |
| The reply never changes the page                    | Check the Callback URL and the `messages` subscription |
| The webhook answers 403                             | `META_APP_SECRET` does not match the Meta app           |
| The gate page says "Wrong gate key"                 | Tap "Forgot gate key?", or send `KEY` from the gate desk |
| The admin page says it is locked                    | Set `ADMIN_KEY`, different from `GATE_KEY`              |
| All visitors get "Too many requests"                | Set `BEHIND_PROXY=true` on Render                       |
| The Tests workflow is red                           | Do not deploy. Read the failed check in the run         |
| The Uptime workflow is red                          | Read "The uptime check" above                           |

Meta reports a lost message later, through the webhook. The app writes each
one to the log as `WhatsApp could not deliver to <number>: error <code>`.

# Safety

This document tells you what the app protects, how it protects it, and what
it does not protect. Read it before real use, and give the known limits to
the people who decide about the campus. To set up the app, read
[setup.md](setup.md). To run it, read [maintenance.md](maintenance.md).

## Who can see what

| Who                      | How                         | Sees                                                 |
|--------------------------|-----------------------------|------------------------------------------------------|
| A visitor                | Their own private link      | Their own request, its status and its current code   |
| An approver              | WhatsApp, from their number | The requests of their own reasons, and any pass they look up |
| A guard                  | The gate key                | Open passes, the gate lists, and the full CSV log    |
| The admin                | The admin key               | Every request, who decided it, and the approver numbers |
| Anybody on the internet  | The public pages            | The forms, the gate desk number, and the health result |

The gate key opens the full CSV log, with every visitor's name, phone number
and address. Give it only to the people at the gate.

## Keys

1. The gate key opens the gate page, the pass lookups and the CSV log. Every
   guard uses the same key.
2. The admin key opens the admin page. It must be different from the gate
   key. If it is not set, or if it is the same, the admin page stays locked,
   because every guard has the gate key.
3. Each page keeps its key in the browser's storage on that device. On a
   shared device, tap Change key when you finish. That removes the key.
4. "Forgot key?" sends the key only to its fixed number: the gate key to
   `GUARD`, and the admin key to `ADMIN_PHONE`. The page never shows the key.
   If `ADMIN_PHONE` is the gate desk number, the admin key is not sent.
5. The server compares keys in constant time, so the time of the answer
   tells nothing about the key.

There is no lockout after wrong keys. Everyone at one gate shares one
internet address, so a lockout after one person's typing mistakes shuts out
the whole gate. Long random keys make guessing useless instead. Use a key
of 20 random characters or more.

## Codes and links

A visit has four identifiers. Each one does one job.

| Identifier  | Example                  | Who has it      | What it can do                         |
|-------------|--------------------------|-----------------|----------------------------------------|
| Reference   | `VR-4022`                | Approvers, gate | Names the request. Opens nothing alone |
| Entry code  | `KT-4821`                | The visitor     | Records the entry, with the gate key   |
| Exit code   | `RM-0937`                | The visitor     | Records the exit, with the gate key    |
| Token       | 22 random characters     | The visitor     | Reads the visitor's own request        |

1. The reference has only 9,000 values, so it is not a secret. At the gate,
   it shows who the visitor is and records nothing.
2. The entry and exit codes come from the Python `secrets` module, so one
   code tells nothing about the next. There are about 5.7 million codes. A
   code works only with the gate key.
3. No message, list or export shows a gate code. Only the visitor's own page
   shows one, and only the code for the next step. A WhatsApp reply repeats a
   code only when the sender typed that code.
4. The token is the visitor's private link. The admin list and the gate never
   receive it.

## Pass expiry

A pass works for `PASS_HOURS` after the request, 48 hours by default. After
that time, nobody can approve the request, and the entry code opens nothing,
on the gate page and on WhatsApp.

1. The time check is part of the same database statement that approves or
   lets the visitor in. A pass cannot expire halfway through an entry.
2. A visitor who is already inside can always leave.
3. The visitor's page stops showing the code at the end time, also with no
   signal.

## WhatsApp

1. When `META_APP_SECRET` is set, the app checks Meta's signature on each
   webhook call and refuses an unsigned or changed call with 403. Keep it set
   in production.
2. The app ignores every number that is not an approver, `GUARD` or
   `ADMIN_PHONE`.
3. The app records each message id, so a message that Meta delivers twice
   runs once.
4. Each reason has its own two approvers. An approver cannot decide the
   request of another reason.
5. A `YES` or `NO` with a reference that does not read correctly decides
   nothing. It never falls back to the request that waits.
6. A field on the form is one line of plain text. The server refuses line
   breaks, control codes and invisible marks, so a visitor cannot add false
   lines to the approver's message.

## The web pages

Every answer from the server has these headers:

| Header                      | What it does                                          |
|-----------------------------|-------------------------------------------------------|
| `Content-Security-Policy`   | Loads scripts, styles and data only from this server  |
| `X-Frame-Options`           | Stops another site from showing a page in a frame     |
| `X-Content-Type-Options`    | Stops the browser from guessing the file type         |
| `Referrer-Policy`           | Sends no address to other sites                       |
| `Strict-Transport-Security` | Makes the browser use HTTPS for one year              |
| `Permissions-Policy`        | Turns off the camera, microphone, location and payment |

The content policy allows inline scripts (`'unsafe-inline'`). The buttons on
the pages call their code from inline `onclick` attributes, and a stricter
policy stops every button. The pages put every visitor-typed text through an
escape function before they show it, so typed text cannot become a script.

A CSV cell that starts with `=`, `+`, `-` or `@` gets a quote in front.
Excel and Sheets run such a cell as a formula, so a name such as
`=HYPERLINK(...)` can otherwise run on the computer that opens the log.

## Limits on requests

| Limit                         | Value                                    |
|-------------------------------|------------------------------------------|
| New requests                  | `REQUESTS_PER_HOUR` from one address, 60 |
| "Forgot key?"                 | 3 from one address, 10 in total, each hour, for each key |
| The health address            | 30 from one address each minute          |

People on one campus Wi-Fi share one address, so the request limit is for a
group, not one person. Raise it if a class tests the app at once.

`BEHIND_PROXY` tells the app where to read the caller's address. On Render, a
proxy adds the real address to the end of `X-Forwarded-For`, and the app
reads the last entry. On your own machine, nothing sets that header, and
trust in it lets anyone invent an address. Set it to `true` only behind a
proxy.

## Privacy

1. The form asks for a name, a phone number, an address, the reason, and the
   person visited. The guard also takes one photo on WhatsApp.
2. The photo stays in the gate desk's WhatsApp chat. The app keeps only
   WhatsApp's id for the photo and the time.
3. The app deletes each visit `RETAIN_DAYS` after the request, 90 days by
   default. The privacy screen states the same number, because it reads it
   from the server.
4. The gate sees the visitor's details while the visit is open. After the
   exit, the gate sees only the times.
5. The phone's copy of the pass holds no phone number and no address. The
   phone deletes the copy when the pass closes or expires.
6. The visitor never sees who approved the request, or that it was approved
   automatically. The number that decided is in the column `decided_phone`.
   Only the admin list sends it. The CSV log does not have it.
7. The health address shows only `true` or `false` for the database and for
   WhatsApp. It never shows a reason or a token.

The CSV log holds every personal detail. Keep downloaded copies on a
protected device, and delete them after the retention period.

## Secrets

| Secret                   | Keep it in                                  |
|--------------------------|---------------------------------------------|
| `DATABASE_URL`           | Render Environment and your own `.env` only |
| `META_TOKEN`             | Render Environment and your own `.env` only |
| `META_APP_SECRET`        | Render Environment and your own `.env` only |
| `GATE_KEY`, `ADMIN_KEY`  | Render Environment, and the people who need them |

Never put a secret in git, in a chat or in a screenshot. `.gitignore` keeps
`.env` out of git. If a secret leaks, change it at its source, then in Render.

## Known limits

Tell the people who decide about the campus about these limits.

1. All guards share one gate key. The log does not say which guard recorded
   an entry.
2. The gate key also opens the full CSV log with personal details.
3. The Record entry button on the gate page lets a visitor in without a
   photo. Only the WhatsApp route asks for one.
4. The app does not check that a visitor's phone number is real.
5. Someone with many internet addresses can send many requests. Each request
   sends a WhatsApp template message, which Meta charges for on a real
   number.
6. The visitor's browser holds the only link to their request. A visitor who
   clears the browser or changes phones must send a new request.
7. The reference has four digits. Keep the visits that the app stores under
   9,000, see [maintenance.md](maintenance.md).
8. On the free Render plan, the app sleeps after 15 quiet minutes. The first
   request after that waits up to about a minute, and reminders and automatic
   approvals wait until the app wakes.
9. With no signal at the gate, the guard cannot check any pass.
10. The content policy allows inline scripts, see "The web pages".

# Running the visitor access app at the university

This document is for the people at the university who decide whether to use
the app, and for the people who will run it. It says what the app does, what
it needs, who does what, and how to test it before full use. The technical
steps are in [setup.md](setup.md), the daily use in
[maintenance.md](maintenance.md), and the security details in
[safety.md](safety.md).

## The problem

A visitor to the campus today waits at the gate while the guard phones the
person or office that the visitor wants to see. Nobody keeps a clear record
of who approved the visit, who let the visitor in, and when the visitor
left. Staff and faculty go through the same gate, and the guard checks them
by face.

## What the app does

1. A visitor fills in a short form on their phone before they come. The form
   asks for their name, phone, address, the reason, and who or which office
   they visit.
2. The approver for that reason or office gets the request on WhatsApp, and
   replies `YES` or `NO` with the reference.
3. The visitor's page shows the decision. An approved visitor gets a pass
   with an entry code. The pass stays on the phone with no signal.
4. At the gate, the guard types the entry code on the gate page, takes a
   photo of the visitor, and records the entry. On the way out, the visitor
   shows an exit code.
5. Staff and faculty on the allow list say a 7-digit code to the guard when
   they come in and when they go out. The guard records the entry or the
   exit, and the person gets a WhatsApp message about each entry.
6. The admin page shows every request, the lists of people, and the logs.

If nobody answers in 15 minutes, the request goes to a backup approver, or
the approver gets a reminder. In working hours, a request that nobody answers
in 30 minutes is approved automatically. An admin can change that time for
each reason and each office on the admin page, or set it to 0, so that a
person must always decide.

The app is designed for weak mobile signal. The visitor page and its pass
work with no signal, and the pages check for news less often when the signal
is bad. Every decision and entry is one database step, so two guards or two
approvers cannot record the same thing twice.

## Roles

| Role        | Who                                      | What they do                                                           |
|-------------|------------------------------------------|------------------------------------------------------------------------|
| Visitor     | Anyone who visits                        | Sends a request, shows the pass at the gate                            |
| Approver    | A staff member for each reason or office | Replies YES or NO on WhatsApp                                          |
| Guard       | Security staff at the gate               | Checks passes and staff codes, takes the photo, records entry and exit |
| Admin       | Office staff who run the app             | Keeps the approvers, offices, allow list, blacklist and guards         |
| Super admin | One or two senior admins                 | Also adds admins, sees gate photos and downloads the logs              |
| Host        | University IT                            | Runs the server, the database and the WhatsApp account                 |

## Who is responsible for what

| Task                                                         | Responsible                               |
|--------------------------------------------------------------|-------------------------------------------|
| Meta, database and hosting accounts, owned by the university | University IT                             |
| Server settings, keys and the WhatsApp token                 | University IT                             |
| Weekly download of the logs, kept on a locked device         | A super admin                             |
| Approvers, offices, allow list and blacklist                 | Admins                                    |
| Guards, their keys, and the paper log for outages            | Security office                           |
| Answering requests within 15 minutes                         | Each approver                             |
| A test of the outage procedure each term                     | Security office and IT                    |
| Changes to the code after handover                           | To be agreed, see "Authorship and rights" |

## Hosting

The demonstration copy runs on Render's free plan with Neon's free database.
Do not use that for real use:

1. The free server sleeps after 15 quiet minutes. The first request after
   that waits up to about a minute.
2. The free database holds about 0.5 GB, roughly 12,000 visits with photos,
   and can be restored only to a time in the last 6 hours.

For real use, the university needs:

1. A server that is always on, approved by university IT. Render's paid plan
   works. A university server works too, if it runs Python 3.11 or newer and
   serves the app over HTTPS.
2. A PostgreSQL database that keeps a restore history of 7 days or more.
3. One app process. The app keeps its reminder timer and some lists in its
   memory, so it must run as one worker (`--workers 1`). Do not add workers
   without a change to the app.
4. The uptime check, or the university's own monitoring, on `/api/health`.

See "The free plans" in [maintenance.md](maintenance.md) for the limits, and
[setup.md](setup.md) for the steps.

## WhatsApp

1. A Meta Business account owned by the university. Meta can ask the
   university to prove its identity.
2. The university's own WhatsApp number for the app. The Meta test number
   reaches only 5 numbers, and the campus has more approvers and guards
   than that.
3. A permanent access token from a Meta system user. A temporary token stops
   after about 24 hours, and a user token stops after about 60 days.
4. Two message templates approved by Meta: `visit_request` and
   `staff_entry`. Their text is in [setup.md](setup.md).
5. Meta charges for some template messages. Check Meta's current WhatsApp
   prices for India before real use.

A plain message reaches a person only if they wrote to the app's number in
the last 24 hours. That is a Meta rule. The approval requests and the staff
entry messages use templates, so they always arrive. The messages to guards
about approvals are plain text, so a guard must write to the app's number
once a day to get them.

## Data the app keeps

| Data                                               | From               | Kept for                     |
|----------------------------------------------------|--------------------|------------------------------|
| Visitor name, phone, address                       | The visitor's form | `RETAIN_DAYS`, 90 by default |
| Reason, person or office visited, people with them | The visitor's form | `RETAIN_DAYS`                |
| Decision, who decided, and the times               | The app            | `RETAIN_DAYS`                |
| Entry and exit times, and the guard                | The gate           | `RETAIN_DAYS`                |
| Gate photo, a small JPEG with no location data     | The gate page      | `RETAIN_DAYS`                |
| Allow list: name, WhatsApp number, code, tag       | An admin           | Until an admin deletes it    |
| Staff entries and exits: name, code, time, guard   | The gate           | `RETAIN_DAYS`                |
| Blacklist: name, number, reason                    | An admin           | Until an admin deletes it    |
| Blocked attempts                                   | The app            | `RETAIN_DAYS`                |
| Admin change log                                   | The app            | `RETAIN_DAYS`                |

The app deletes old records by itself, at least once an hour. It collects no
ID number, no location and no vehicle number. The visitor's privacy screen
says what the app keeps, and that the guard takes one photo at the gate.

### The gate photo

1. The photo taken on the gate page is the record. The app stores it with the
   visit, and an admin sees it only after tapping View photo.
2. A guard can also send the photo on WhatsApp, for example when the gate
   page does not work. The app records the time of that photo, but it does
   not keep the photo. It stays in the guard's WhatsApp chat.
3. The university decides how long guards keep WhatsApp photos on their
   phones, and tells the guards. The app cannot delete them.

## Who sees what

| Role              | Sees                                                                                                                                   | Does not see                                          |
|-------------------|----------------------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| Visitor           | Their own request and pass, through a private link on their phone                                                                      | Anyone else's request                                 |
| Approver          | For their reason or office: the reference, name, phone, address, reason, person visited, people with them                              | Requests for other reasons                            |
| Guard             | The pass's name, reason, person visited, people with them, status and codes; who is inside and expected; a staff member's name and tag | The visitor's phone and address, the history, any log |
| Allow list person | A message about each of their own entries                                                                                              | Anything else                                         |
| Admin             | Everything on the admin page except the gate photos: requests, the lists, the change log                                               | Keys of other people                                  |
| Super admin       | As an admin, and each gate photo, the downloads, and adding or removing admins                                                         | Keys of other people                                  |
| Host              | The database and the server settings                                                                                                   | Nothing is hidden from the host                       |

## WhatsApp keeps its own copies

The app deletes its records after `RETAIN_DAYS`. WhatsApp does not: the
approvers' and guards' chats keep each request, reply and photo until the
person deletes them, and a phone backup to a personal cloud keeps them too.

1. The university decides how long those chats may keep visitor details and
   photos, and tells the approvers and guards.
2. For photos, prefer the gate page. Its photo stays in the app's database,
   and the app deletes it on time.
3. Consider WhatsApp's disappearing messages, or a phone with no personal
   cloud backup, for the gate desk.

## Backups and recovery

1. A super admin uses Download logs each week, and keeps the two files on a
   locked device. On the free database this is the only backup older than 6
   hours.
2. On a paid database, the university also gets the database's own restore
   history.
3. To restore, the host restores the database to a time before the problem,
   then restarts the app. See "Where the data lives" in
   [maintenance.md](maintenance.md).

The targets to agree on before the pilot:

| Target                      | On the free plans | On a paid database |
|-----------------------------|-------------------|--------------------|
| Data that can be lost (RPO) | Up to one week    | Minutes            |
| Time to be back up (RTO)    | About an hour     | About an hour      |
| Who restores                | University IT     | University IT      |

Test a restore once before the pilot: restore a copy of the database to a new
branch in Neon, point a test copy of the app at it, and check that the
visits, the passes, the blacklist, the allow list and the change log are
there.

## When the system is down

The gate page needs the server to check a pass. With no server, or no signal
at the gate, the guard cannot check any pass, on the page or on WhatsApp. The
gate page shows "Offline" at the top, and keeps the last lists it loaded,
with the time they are from.

Keep a printed paper log at the gate for these times. Its columns: date, time
in, name, phone, person or office visited, pass code or "none", how the visit
was checked, guard's name, time out.

1. A visitor with an approved pass: their pass shows on their phone with no
   signal. The guard cannot check the code with the server. Read the name on
   the pass, phone the person or office they visit to confirm, and write the
   code in the paper log.
2. A visitor with no pass: phone the approver for that reason or office.
   Write the approver's name and the time of their answer in the paper log.
3. Staff and faculty: check them as the security office decides, for example
   by the campus ID card. Write their name and time.
4. The blacklist does not work offline. Keep a printed copy of the
   blacklist at the gate, and print a new one after each change.
5. When the system works again, and a visitor from the paper log with a
   pass code leaves, the guard first records the entry: the entry code and a
   photo, as for a new entry. The visitor's pass then shows the exit code,
   and the guard records the exit. The paper log keeps the real time in.
6. For the visitors who left while the system was down, record nothing in
   the app. Their pass stays usable until it expires, `PASS_HOURS` after the
   request, because the app cannot cancel an approved pass. Until then,
   before a guard lets someone in with a code, the guard makes sure that the
   code is not in the paper log.
7. The same day, a super admin compares the paper log with the visit log on
   the admin page. Each line needs a pass code or the name of the approver
   who answered. Report a line with neither to the security office.
8. A super admin keeps the paper pages with that week's downloaded logs, for
   `RETAIN_DAYS`.

If only WhatsApp is down, the gate page still works for passes that are
already approved. New requests cannot reach approvers. Use step 2 for new
visitors.

Test this procedure once each term: turn off the gate phone's data and walk
through steps 1 to 8.

## Security

The main points, in full in [safety.md](safety.md):

1. Each guard and each admin has their own key. The app stores only a hash
   of each key, and the logs name the person whose key was used.
2. Approvers are known by their WhatsApp number. A message from any other
   number cannot decide a request.
3. Only a super admin can download the logs and the photos.
4. The admin page signs out after 30 minutes with no use, and has a button
   to sign out. The gate page has a Lock button.
5. The admin page runs with a strict content policy, so an injected script
   cannot run there.
6. Every change on the admin page goes into the change log, with the name of
   the admin.

## Known limits

The full list is "Known limits" in [safety.md](safety.md). The most important
for a decision:

1. A visitor is known only by a phone number that the app does not check.
2. The blacklist knows only phone numbers. It cannot stop a person who uses
   another phone, or who comes as a guest on someone else's request.
3. People with a visitor are named, but the guard checks only the person
   whose pass it is.
4. The app records no exit for staff and faculty.
5. With no signal at the gate, nothing can be checked. See "When the system
   is down".
6. The app runs as one process. It suits one campus, not many.

## Pilot

1. Week 1: University IT sets up the accounts, the server and the WhatsApp
   number, using [setup.md](setup.md). Admins add the approvers, two or three
   offices, the guards of one gate, and about 20 staff on the allow list.
2. Weeks 2 and 3: one gate uses the app for visitors, and keeps the current
   method next to it. The guards use the paper log once, as a test.
3. Week 4: the people involved review the results against the criteria
   below, and decide on the other gates.

## Acceptance criteria

The pilot passes when, over its two weeks:

1. Every entry in the app has an approved pass or an allow list code, a guard
   name and, for visitors, a gate photo.
2. No visitor enters on a pass that was declined, expired or blacklisted.
3. Most requests are decided within 15 minutes. The university sets the
   share it accepts.
4. Approvers get each request on WhatsApp, and staff get each entry message.
5. Admins add a guard, an office and a blacklisted number with no help.
6. The uptime check shows no failure that lasted more than 15 minutes.
7. The outage test with the paper log is done once.
8. A record older than `RETAIN_DAYS` is gone from the database.

## Authorship and rights

Settle these questions in writing before the handover. This document does not
answer them, and it is not legal advice.

1. Who owns the code: the developer, the university, or both?
2. What may the university do with it: use it, change it, give it to others?
3. Under which license is the code shared? The repository has no license
   file yet.
4. Who maintains the code after handover, for how long, and on what terms?
5. Which data and accounts belong to the university, and which to the
   developer, during the pilot?

## Permission to show the project

Also settle these in writing:

1. May the developer show the project in a portfolio, on GitHub, on LinkedIn,
   in a CV, and in presentations and competitions?
2. May the developer say "deployed at Vijaybhoomi University", and from which
   date?
3. May the developer use the university's name and logo with the project?
4. Will the university give a letter that confirms the deployment and the
   developer's authorship?

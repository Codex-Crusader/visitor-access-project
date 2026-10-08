# Setup

This document tells you how to set up the visitor access app on new accounts,
and what each setting does. Do the steps in order. To use and look after a
running app, read [maintenance.md](maintenance.md). For security and privacy,
read [safety.md](safety.md).

In these documents, `<address>` means the web address of your copy of the
app, for example `https://your-app.onrender.com`. Render gives you this
address in step 4.

## What you need

You need four free accounts: Meta for developers, Neon, Render and GitHub.
The setup takes about an hour, plus the time that Meta takes to approve the
message template.

The free plans are for a demonstration and a test only. Real use needs a
server that is always on and a database with a longer restore history. See
steps 14 and 15 of "Before real use", and "Hosting" in
[university-deployment.md](university-deployment.md).

## Step 1: WhatsApp on Meta

1. On https://developers.facebook.com, create an app and add WhatsApp to it.
2. Open WhatsApp, then API Setup. Copy the Phone number ID. This is
   `META_PHONE_NUMBER_ID`.
3. On the same page, add each approver, guard and allow list phone number to the
   recipient list. A Meta test number sends only to numbers on that list,
   and the list holds 5 numbers at most. If more people must get messages,
   add the campus's own WhatsApp number first, see step 7.
4. Open App settings, then Basic. Copy the App secret. This is
   `META_APP_SECRET`. The app does not start without it.
5. Make a permanent access token. In Meta Business settings, open Users, then
   System users. Add a system user, give it your app with full control, and
   click Generate token. Pick the permissions `whatsapp_business_messaging`
   and `whatsapp_business_management`, and pick Never for expiry. This is
   `META_TOKEN`.
6. In WhatsApp Manager, open Message templates, and create the template
   `visit_request`. See "The approval template" below. Meta must approve it
   before the app can send requests.

Do not use the temporary token from API Setup. It stops working after about
24 hours, and then no request reaches an approver.

## Step 2: The database on Neon

1. On https://neon.tech, create a project. Pick the region nearest to your
   campus, and use the same region on Render in step 4. For a campus in
   India, pick AWS Asia Pacific 1 (Singapore).
2. Click Connect, and copy the connection string. This is `DATABASE_URL`.
   Use the pooled string, the one whose host name contains `-pooler`.

The connection string holds the database password. Paste it only into Render
and into a `.env` file on your own machine. Never put it in git or in a chat.

## Step 3: The code on GitHub

The app is in the `application/` folder of the project repository,
https://github.com/Codex-Crusader/visitor-access-project. The file
`render.yaml` is at the top of the repository, next to that folder. Keep
this layout. Render looks for the app in `application/`, and the setup
fails if the app is at the top.

1. Sign in to GitHub with the campus account.
2. Open https://github.com/new/import, and type the project repository's
   address. Pick the campus account as the owner, and pick Private. The
   copy then belongs to the campus, and it stays when the original changes
   or goes away.
3. In the copy, make sure that `render.yaml` and the `application/` folder
   are at the top.

If you got the code as files and not as a link, make a new private
repository. Upload the files so that `render.yaml` and the `application/`
folder are at the top.

The `.gitignore` file keeps `.env` out of the repository. The copy holds no
key or password. Those go only into Render, in step 4.

## Step 4: The app on Render

The file `render.yaml`, at the top of the repository, describes the service:
its region, its commands, and the settings that have a fixed value. Render
reads it as a Blueprint, so you type only the values that are yours.

1. On https://render.com, click New, then Blueprint, and pick the repository.
   The first time, Render asks to connect your GitHub account. Give it
   access to the campus copy from step 3.
2. Render shows the service from `render.yaml` and asks for each value that
   the file leaves empty. Type them. "Settings" below says what each one is.
3. Click Apply. When Render says Live, it shows the app's address at the top
   of the service's page. This is `<address>`.

To make the service by hand instead, click New, then Web Service. Type the
values from `render.yaml`: the Root Directory, the build command
`pip install -r requirements.txt`, the start command
`gunicorn app:app --workers 1 --threads 4 --timeout 60`, and every setting,
also `BEHIND_PROXY` and `PYTHON_VERSION`.

The app builds its database tables by itself the first time it starts.

Keep `--workers 1`. The timer that sends reminders runs inside the worker,
so a second worker sends every reminder twice. The worker also keeps the
gate board and the visitors' status in memory, and only its own writes
clear them, so a second worker shows old lists.

## Step 5: Connect WhatsApp to the app

1. In the Meta app, open WhatsApp, then Configuration.
2. In Callback URL, type `<address>/webhook/whatsapp`.
3. In Verify token, type the same word as `META_VERIFY_TOKEN`.
4. Click Verify and save.
5. Under Webhook fields, subscribe to `messages`.

If you do not subscribe to `messages`, the app never receives the approvers'
replies. People often miss this step.

## Step 6: Try it

1. Open `<address>` on a phone, and send a request as a visitor.
2. The approver gets a WhatsApp message. Reply `YES` and the reference.
3. Within a few seconds, the visitor's page shows Approved.
4. Open `<address>/gate`, type the gate key and the entry code, take a photo
   of the visitor, and record the entry.
5. Open `<address>/api/health`. It must show `"database":true` and
   `"whatsapp":true`.

If the approver gets nothing, read the Render log. Then read "When something
fails" in [maintenance.md](maintenance.md).

## Step 7: Before real use

Do these steps before visitors use the app. A copy made for a demonstration
does not have them.

1. Run the app on the campus's own accounts: Meta, Neon, Render and GitHub.
   Steps 1 to 6 make a new copy there.
2. Set `GATE_KEY` and `ADMIN_KEY` to random keys of 20 characters or more,
   different from each other. To make one, run
   `python -c "import secrets; print(secrets.token_urlsafe(24))"`.
   See "Change a key" in [maintenance.md](maintenance.md).
3. Use a permanent `META_TOKEN`, as step 1 tells you.
4. Move from Meta's test number to the campus's own WhatsApp number. In the
   Meta app, open WhatsApp, then API Setup, and add your phone number. Put its
   Phone number ID in `META_PHONE_NUMBER_ID`. Create the `visit_request`
   template again for that WhatsApp account, and wait until Meta approves it.
   Meta can ask the business to prove its identity first.
5. Set `ADMIN_PHONE` to the admin's WhatsApp number. It must not be the gate
   desk number or a guard's number, or "Forgot admin key?" stays off.
6. Set the approver numbers for each reason, on the admin page or with
   `APPROVERS`.
7. Turn on the uptime check. See "The uptime check" in
   [maintenance.md](maintenance.md).
8. Add the guards in the admin page's Guards part, and give each guard the
   key that shows. Give `<address>` to visitors, the gate key to the gate
   desk, and the admin key to the admin.
9. Add the offices in Approvers & offices, the staff in Allow list, and any
   other admins in Admins.
10. Create the `staff_entry` template, and set `STAFF_ENTRY_TEMPLATE`. See
    "The allow list entry template".
11. Set `GATE_DESK_PHONE` to the gate desk's real phone number. The example
    number `+912200000000` rings nobody, and visitors see it on Call gate
    desk.
12. Delete the demonstration data on the admin page: test offices, test
    people on the allow list, and approver numbers that belong to the
    developer.
13. When each guard has their own key, change `GATE_KEY` to a new random
    key. Keep the new key in a safe place as a spare.
14. Move the database to a plan that keeps a restore history of 7 days or
    more, such as a paid Neon plan. The free plan keeps only 6 hours. Also
    use Download logs each week, and keep both files on a locked device.
15. Move the app to a server that is always on: a paid Render plan, or a
    university server that IT approves. Do not use the free plan for real
    use. It sleeps after 15 minutes with no use, and the first request or
    WhatsApp reply after that waits about a minute.

While a server setting still has a demo value, the admin page shows "Before
real use" at the top, with each setting and what it changes. It names the
gate desk number, `ADMIN_PHONE`, `STAFF_ENTRY_TEMPLATE` and
`TEMPLATE_FALLBACK`. The list goes away when each one is set. It cannot see
the Meta test number or the token's expiry date, so do steps 3 and 4 from
this list.

## Settings

Set these in the Render Environment page, or in `.env` on your own machine.
The first group is required.

| Name                   | Value                                                 |
|------------------------|-------------------------------------------------------|
| `META_TOKEN`           | The permanent token from step 1                       |
| `META_PHONE_NUMBER_ID` | The Phone number ID from step 1                       |
| `META_VERIFY_TOKEN`    | Any word. Type the same word on the Meta webhook page |
| `META_APP_SECRET`      | The App secret from step 1                            |
| `MAIN_APPROVER`        | The approver's number, like `+911234567890`           |
| `GATE_KEY`             | The gate page password. 20 characters or more         |
| `GATE_DESK_PHONE`      | The number on the Call gate desk button               |
| `DATABASE_URL`         | The connection string from step 2                     |

These have a default. Set the ones that apply to you.

| Name                     | Value                                                        |
|--------------------------|--------------------------------------------------------------|
| `BACKUP_APPROVER`        | The backup approver. Default: `MAIN_APPROVER`                |
| `APPROVERS`              | JSON: other approvers for some reasons. See below            |
| `GUARD`                  | The gate desk's WhatsApp number. Default: `MAIN_APPROVER`    |
| `ADMIN_PHONE`            | Gets the admin key on request. Default: `MAIN_APPROVER`      |
| `ADMIN_KEY`              | The admin page password, 20 characters or more               |
| `BEHIND_PROXY`           | `true` on Render. Leave it unset on your own machine         |
| `ESCALATE_MINUTES`       | Minutes before the backup approver is asked. Default 15      |
| `AUTO_APPROVE_MINUTES`   | Default minutes before automatic approval. 0 is off. 30      |
| `WORK_HOURS`             | Working hours, in whole hours. Default `10-17`               |
| `WORK_DAYS`              | Working days. Default `Mon,Tue,Wed,Thu,Fri,Sat`              |
| `WORK_TIMEZONE`          | The clock for working hours. Default `Asia/Kolkata`          |
| `PASS_HOURS`             | Hours a pass works after the request. Default 48             |
| `RETAIN_DAYS`            | Days a record is kept before deletion. Default 90            |
| `REQUESTS_PER_HOUR`      | New requests from one address in one hour. Default 60        |
| `REQUESTS_PER_HOUR_ALL`  | New requests from all addresses in one hour. Default 300     |
| `REQUEST_TEMPLATE`       | The approval template. Default `visit_request`               |
| `TEMPLATE_LANGUAGE`      | The language code of that template. Default `en`             |
| `TEMPLATE_FALLBACK`      | `true` sends plain text when the template fails. Off         |
| `STAFF_ENTRY_TEMPLATE`   | The allow list entry template. Unset sends plain text        |
| `PYTHON_VERSION`         | The Python that Render uses. `render.yaml` sets `3.14.3`     |
| `ALLOW_UNSIGNED_WEBHOOK` | `true` runs without `META_APP_SECRET`. Your own machine only |

Write every phone number in E.164 form: a plus sign, the country code, then
the number.

The app checks the unsafe settings when it starts, and the Render log says
what to fix:

1. Without `META_APP_SECRET`, the app does not start. Without the secret,
   anyone who finds the webhook address can send a false YES or IN.
2. With a `GATE_KEY` shorter than 20 characters, or the example from
   `.env.example`, the app does not start.
3. Without `ADMIN_KEY`, with one shorter than 20 characters, or with the same
   value as `GATE_KEY`, the admin page stays locked. The rest of the app runs.

`REQUESTS_PER_HOUR` counts requests from one internet address. A whole
campus Wi-Fi can be one address, so before a large event with visitors on
the campus Wi-Fi, raise it, for example to 300.

`REQUESTS_PER_HOUR_ALL` counts the requests from every address together. Each
request sends a WhatsApp template to an approver, so this cap stops a flood of
messages from many addresses, and Meta's charges with it. After the cap, the
visitor page asks the visitor to call the gate desk. Before a large event,
raise it on Render.

`ADMIN_PHONE` must not be the gate desk number (`GUARD`). If it is, "Forgot
admin key?" is refused, because a guard must never get the admin key.

`BEHIND_PROXY` must be `true` on Render. If it is not set, the app counts
every visitor as the same caller, and 60 requests in one hour stop the whole
campus. Render reads `render.yaml` only for a service made from a Blueprint,
so set the value on the service's own Environment page.

`RETAIN_DAYS` and `PASS_HOURS` also appear in the visitor's privacy screen
and pass. The pages read them from the server, so the text always matches.

### Approvers for each reason

Each reason on the form has a main approver and a backup approver. The
reasons are `See a student`, `See an office`, `Delivery`, `Event` and `Other`.
They are the same list as `REASONS` in `core/config.py` and `static/visitor.js`. A
reason that the visitor types in counts as `Other`. `See an office` has no
pair of its own: each office has its own pair in Approvers & offices, and an
office visit with no office goes to the pair for `Other`. `APPROVERS` may
name `See an office`, but the app does not use it.

Every reason uses `MAIN_APPROVER` and `BACKUP_APPROVER`, unless `APPROVERS`
names it. `APPROVERS` is JSON, and it names only the reasons that differ:

```
APPROVERS={"Delivery": ["+919000000001", "+919000000002"], "Event": ["+919000000003", "+919000000004"]}
```

A reason name that is not on the list stops the app at start, so a typing
mistake cannot send a reason to the wrong person. The admin page can also set
each reason's numbers. A pair saved there wins over the settings. Put each
new number on the Meta recipient list while the app uses a test number.

### Automatic approval in working hours

When no approver answers a request made in working hours, the app approves it
after a set time. Working hours are 10:00 to 17:00, Monday to Saturday, India
time. 10:00 counts, and 17:00 does not.

Each reason and each office has its own time, set on the admin page under
Approvers & offices. A reason or office with no time set uses
`AUTO_APPROVE_MINUTES`, 30 by default. A time of 0 means that a person must
always decide.

1. The app stores the approval time when the request is made. A request made
   outside working hours has no approval time. It waits for YES or NO.
2. A YES or a NO before that time wins.
3. When the app approves, both approvers get a plain WhatsApp message. An
   approver who has not written to the number in 24 hours can miss it.
4. The admin page and the CSV show `auto` as the decider. The visitor never
   sees how the request was approved.
5. When an admin changes a time, each open request that waits for automatic
   approval gets the new time at once. A time of 0 stops it. A request that
   had no approval time keeps none.

To turn this off everywhere, set `AUTO_APPROVE_MINUTES=0`, and set no time on
the admin page.

## The approval template

WhatsApp delivers plain text only to a person who wrote to your business
number in the last 24 hours. Outside that window, Meta accepts the message,
answers 200, and then drops it. The app sees no error. So the approval
request goes out as the template `visit_request`, which WhatsApp delivers at
any time.

The template has the category Utility, the language `en`, and this body:

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

`{{1}}` is the reference. `{{2}}` says if this is a new request, a request for
the backup approver, or a reminder to an approver who has no backup. The rest are the visitor's details. Replies to the
approvers' and the guards' own commands stay plain text, because that person
just wrote to the number. The message to the gate desk about an approval is
plain text too, so it reaches the desk phone only if it wrote in the last 24
hours.

`TEMPLATE_FALLBACK` controls what happens when Meta refuses the template:

1. Not set, the default: the visitor sees "Could not reach the approver" and
   can try again. Use this in production.
2. `true`: the app sends plain text and writes `Approval template refused` to
   the log. Use this only while Meta reviews a new template. Delete the
   setting when the template shows Approved in WhatsApp Manager.

A refusal is different from no clear answer. If Meta does not answer in 15
seconds, or answers with a fault on its own side, the message can still
arrive. The app then keeps the request, and the visitor sees it as waiting.
The reminder after `ESCALATE_MINUTES` asks again, and the request is never
approved by itself, so a person always sees it. The log says
`WhatsApp send uncertain`.

Leave the fallback off in production. Meta can pause a template, for example
after low quality ratings. With the fallback on, every request then goes out
as plain text, which a quiet approver does not get, and the visitor is told
that the request went out.

If you make a new Meta app or WhatsApp account, create the template again
with the same name and body.

## The allow list entry template

When a guard records an allow list entry, the person gets a WhatsApp message.
Most of them do not write to the app's number every day, so the message must
be a template to arrive. Create it in WhatsApp Manager with the name
`staff_entry`, the category Utility, the language `en`, and this body:

```
Campus entry recorded for {{1}} at {{2}} by {{3}}.

If this was not you, tell the campus admin.
```

`{{1}}` is the person's name, `{{2}}` is the time, and `{{3}}` is the
name of the guard, without their number. Meta refuses a body that starts or ends with a value, so keep the
fixed words around them. When Meta approves it, set `STAFF_ENTRY_TEMPLATE=staff_entry` on
Render. Until then, the app sends the same text as plain text, which arrives
only if the person wrote to the app's number in the last 24 hours. A failed
message never stops the entry, and the log names the code.

## Run it on your own machine

Use a separate Neon branch for your own machine, so a test visit never
appears in the live list. A branch is a copy of the database that you can
change on its own. Make one in the Neon console under Branches.

1. Make a Python environment in the app's folder, install the packages, and
   copy the example settings.

   ```
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   copy .env.example .env
   ```

2. Fill in `.env`. Then check it. This sends one test message to
   `MAIN_APPROVER`.

   ```
   .venv\Scripts\python.exe tools\check_setup.py
   ```

3. Start the server.

   ```
   .venv\Scripts\python.exe app.py
   ```

4. Open http://127.0.0.1:5000 for the visitor app, and
   http://127.0.0.1:5000/gate for the gate desk.
5. Meta must reach your webhook from the internet. Open a tunnel in a second
   terminal.

   ```
   cloudflared tunnel --url http://localhost:5000
   ```

6. Put the printed address plus `/webhook/whatsapp` in the Meta
   Configuration page, as in step 5, and subscribe to `messages`.

## Demo run

1. Open `<address>` and send a request.
2. Read the WhatsApp message on your phone.
3. Reply `YES VR-40221`, with the reference from the message.
4. The page turns green and shows the entry pass with its entry code.
5. Send `IN` and the entry code on WhatsApp, for example `IN KT-4821`. The
   reply asks for a photo.
6. Take a photo in the same chat and send it. You can also use `/gate` in a
   browser for steps 5 and 6. There, the page asks for the photo before it
   records the entry.
7. The visitor page changes to "Inside campus", and the pass shows the exit
   code.
8. Send `OUT` and the exit code. The visitor page says "Visit complete".
9. Send the exit code again. The reply says that the pass is closed.

To show a decline, reply `NO` and the reference. To show escalation, set
`ESCALATE_MINUTES=1` and restart. Send a request and do not reply. After one
minute, the backup approver gets the same details. An approver with no backup
gets a reminder.

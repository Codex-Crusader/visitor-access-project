# User Manual

This manual tells you how to set up the visitor access app, and what each
person who uses it does. The README explains how the app works inside.

In this manual, `<address>` means the web address of your copy of the app,
for example `https://your-app.onrender.com`. Render gives you this address in
step 4 of the setup. Give it to visitors, guards and admins. If the address
changes, give them the new one.

## Who does what

| Role     | Uses                       | Job                                       |
|----------|----------------------------|-------------------------------------------|
| Visitor  | The web page on a phone    | Asks to come in, and shows the pass       |
| Approver | WhatsApp                   | Says yes or no to each request            |
| Guard    | The gate page, or WhatsApp | Records each entry and exit               |
| Admin    | The admin page             | Reads every request and downloads the log |

## Set up the app

You need four free accounts: Meta for developers, Neon, Render and GitHub.
The setup takes about an hour, plus the time Meta takes to approve the
message template.

### Step 1: WhatsApp on Meta

1. On https://developers.facebook.com, create an app and add WhatsApp to it.
2. Open WhatsApp, then API Setup. Copy the Phone number ID. This is
   `META_PHONE_NUMBER_ID`.
3. On the same page, add each approver and guard phone number to the
   recipient list. A Meta test number sends only to numbers on that list.
4. Open App settings, then Basic. Copy the App secret. This is
   `META_APP_SECRET`.
5. Make a permanent access token. In Meta Business settings, open Users, then
   System users. Add a system user, give it your app with full control, and
   click Generate token. Pick the permissions `whatsapp_business_messaging`
   and `whatsapp_business_management`, and pick Never for expiry. This is
   `META_TOKEN`. Do not use the temporary token from API Setup, because it
   stops working after about 24 hours.
6. In WhatsApp Manager, open Message templates, and create the template
   `visit_request`. Use the category Utility, the language English (`en`),
   and the body in the README section "The approval template". Meta must
   approve it before the app can send requests.

### Step 2: The database on Neon

1. On https://neon.tech, create a project. Pick the region nearest to your
   campus, and use the same region on Render in step 4. For a campus in
   India, pick AWS Asia Pacific 1 (Singapore).
2. Click Connect, and copy the connection string. This is `DATABASE_URL`.

The connection string holds the database password. Paste it only into
Render, and into a `.env` file on your own machine. Never put it in git or
in a chat.

### Step 3: The code on GitHub

Put this folder in a GitHub repository. The `.gitignore` file keeps `.env`
out of the repository.

### Step 4: The app on Render

1. On https://render.com, click New, then Web Service, and pick the
   repository. If the app is in a subfolder of the repository, type that
   folder in Root Directory. Pick the same region as the database, and the
   Free plan.
2. Type the same commands as `render.yaml`. The build command is
   `pip install -r requirements.txt`. The start command is
   `gunicorn app:app --workers 1 --threads 4 --timeout 60`.
3. In Environment, set each value in this table.

   | Name                   | Value                                         |
   |------------------------|-----------------------------------------------|
   | `META_TOKEN`           | The permanent token from step 1               |
   | `META_PHONE_NUMBER_ID` | The Phone number ID from step 1               |
   | `META_APP_SECRET`      | The App secret from step 1                    |
   | `META_VERIFY_TOKEN`    | Any word you choose. You need it in step 5    |
   | `MAIN_APPROVER`        | The approver's number, like `+911234567890`   |
   | `BACKUP_APPROVER`      | The backup approver's number                  |
   | `GUARD`                | The gate desk's WhatsApp number               |
   | `ADMIN_PHONE`          | The admin's WhatsApp number                   |
   | `GATE_DESK_PHONE`      | The number on the Call gate desk button       |
   | `GATE_KEY`             | The password for the gate page                |
   | `ADMIN_KEY`            | The password for the admin page               |
   | `DATABASE_URL`         | The connection string from step 2             |
   | `BEHIND_PROXY`         | `true`                                        |

   Write each phone number with a plus sign and the country code. Make
   `GATE_KEY` and `ADMIN_KEY` different. If they are the same, the admin page
   stays locked. The README lists more settings, each with a default.
4. Click Deploy. When Render says Live, it shows the app's address at the
   top of the page. This is `<address>`.

The app builds its database tables by itself the first time it starts.

### Step 5: Connect WhatsApp to the app

1. In the Meta app, open WhatsApp, then Configuration.
2. In Callback URL, type `<address>/webhook/whatsapp`.
3. In Verify token, type the same word as `META_VERIFY_TOKEN`.
4. Click Verify and save.
5. Under Webhook fields, subscribe to `messages`. If you skip this, the app
   never hears the approver's replies.

### Step 6: Try it

1. Open `<address>` on a phone, and send a request as a visitor.
2. The approver gets a WhatsApp message. Reply `YES` and the reference.
3. Within a few seconds, the visitor's page shows Approved.
4. Open `<address>/gate`, type the gate key and the entry code, and record
   the entry.

If the approver gets nothing, read the Render log. Then read the section
"When something fails" in the README.

## Visitor

1. Open `<address>` on your phone.
2. Tap Request a Visit.
3. Fill in your name, phone number and address, then tap Continue.
4. Pick the reason for the visit, and type the person you visit. Add your
   guests if any come with you. Tap Review.
5. Read the details, then tap Send request. Keep the page open.
6. Wait for the decision. The page shows it within a few seconds of the reply.
7. If the request is approved, tap Open pass, and show the entry code to the
   guard.
8. After the guard lets you in, the pass shows a different code, the exit
   code. Show it to the guard when you leave.

After the exit, the pass closes and both codes stop working. If the page
says the request was declined, do not go to the gate. Use the Call gate desk
button for help.

Your phone keeps a copy of your pass. If the signal at the gate is weak or
gone, open the page anyway: it shows the pass from the copy and says when it
was last updated. It updates by itself when the signal comes back.

On the free Render plan, the app sleeps after 15 minutes with no use. After
your first visit, the page still opens at once, but the status can take up to
a minute to update while the app wakes.

## Approver

You get a WhatsApp message with the visitor's details and a reference such as
`VR-4022`.

1. To approve, reply `YES VR-4022`.
2. To decline, reply `NO VR-4022`.

If only one request is waiting, `YES` or `NO` alone is enough. Send any other
message to see the requests that wait for you.

If you do not answer in time, the backup approver gets the same request. The
time is `ESCALATE_MINUTES`, 15 minutes unless you change it. The first reply
decides. A reply after that changes nothing.

If the request was made between 10:00 and 17:00, Monday to Saturday, and no
one answers in 30 minutes, the app approves it automatically. Both approvers
get a message that says so. To stop a visitor, reply `NO` before that time.

## Guard

You can work from the gate page or from WhatsApp. Both record the same thing.

### On the gate page

1. Open `<address>/gate`.
2. Type the gate key. The page asks for it once on each phone. If you do not
   know it, tap "Forgot gate key?". The app sends the key to the gate desk
   WhatsApp. If it does not arrive, send `KEY` from the gate desk phone to the
   app's WhatsApp number.
3. Type the code on the visitor's pass in the box, and tap Check pass. Small
   letters and spaces are fine, for example `kt 4821`.
4. If the pass is approved, tap Record entry.
5. When the visitor leaves, type the exit code, tap Check pass, then tap
   Record exit.
6. Tap Next visitor to clear the screen.

The page also shows two lists. Inside now lists everyone who is on campus. A
yellow row means the visitor has been inside for more than 8 hours. Expected
lists the passes approved in the last 24 hours that nobody has used yet. A tap
on a name only shows details. It records nothing.

Download log saves every visit as a CSV file.

### On WhatsApp

1. Send `IN` and the entry code, for example `IN KT-4821`.
2. The app asks for a photo of the visitor. Take it in the same chat and send
   it within 10 minutes. The photo records the entry.
3. When the visitor leaves, send `OUT` and the exit code, for example
   `OUT RM-0937`.

To look at a pass without recording anything, send only the code or the
reference.

### When the gate says no

| The gate says          | Do this                                     |
|------------------------|---------------------------------------------|
| Not approved yet       | Do not let the visitor in. Ask them to wait |
| Declined               | Do not let the visitor in                   |
| ... is the exit code   | Ask for the entry code                      |
| This pass is closed    | The visit is over. The code is dead         |
| Wrong gate key         | Tap "Forgot gate key?", then type the key   |

## Admin

1. Open `<address>/admin`.
2. Type the admin key. It is different from the gate key. If you do not know
   it, tap "Forgot admin key?". The app sends the key to `ADMIN_PHONE` on
   WhatsApp. If it does not arrive, send `KEY` from that phone to the app's
   WhatsApp number.
3. Tap a tile to show only the requests with that status.
4. Use the search box to find a name, phone number, reference or the person
   visited.
5. Tap a request to see all its details and times.
6. Use Download CSV to save the whole log.

### Change the approvers

1. At the end of the admin page, find "Who approves each reason".
2. Tap Change on the reason.
3. Type the approver's number and the backup's number. Write each one with
   `+` and the country code, like `+919876543210`. Both are required, and
   they must differ.
4. Tap Save both numbers.

The change works at once. New requests go to the new numbers, and the old
numbers can no longer decide that reason's requests. While the app uses
Meta's test number, also add each new number to the recipient list in Meta's
API Setup page.

## Look after the app

### Where the data lives

The visits live in the Neon database. When Render deploys a new version, the
visits stay. The app deletes each visit after `RETAIN_DAYS`, 90 days unless
you change it, as the privacy screen promises.

### Change a key

Use long random keys for real use. Short demo keys are easy to guess.

1. Open the service on Render, then Environment.
2. Change `GATE_KEY`, `ADMIN_KEY`, or both. The two keys must differ.
3. Click Save, rebuild, and deploy.
4. Give the new gate key to each guard. Each gate page asks for it once.

### Change the address

If you move the app and its address changes, do two things. Give the new
address to visitors, guards and admins. Then change the Callback URL in step
5 of the setup, or the app stops hearing WhatsApp replies.

### Limits of the free plans

1. Render sleeps after 15 quiet minutes. While it sleeps, the backup
   approver gets no reminders. They go out when the app wakes.
2. Neon gives 100 compute hours a month, about 13 hours a day awake. If the
   hours run out, the app stops working until the next month.
3. Neon holds 0.5 GB. That is room for far more than 90 days of visits.

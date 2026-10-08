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
| Allowed  | Their 7-digit code         | Enter and leave with no request           |
| Admin    | The admin page             | Reads every request and downloads the log |

## Visitor

1. Open `<address>` on your phone.
2. Tap Request a Visit.
3. Fill in your name, phone number and address, then tap Continue. A phone
   number has 10 digits. A visitor from abroad types `+` and the country
   code, such as `+44 7911 123456`.
4. Pick the reason for the visit, and type the person you visit. For See an
   office, pick the office from the list.
5. To add the people who come with you, tap Add a person and type a name.
   Tap Add another person for each next name, up to 10 people. Tap Review.
   To stop and come back, tap Finish later, then Save and exit. The phone
   keeps what you typed for 7 days. Nothing goes to the server.
6. Read the details, then tap Send request. Keep the page open. If the page
   says the request was not sent, tap Send request again: if the first one
   did reach the server, you get that request back, and the approver is not
   asked twice.
7. Wait for the decision. The page shows it a few seconds after the reply.
8. If the request is approved, tap Open pass, and show the entry code to the
   guard.
9. After the guard lets you in, the pass shows a different code, the exit
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
`VR-40221`.

1. To approve, reply `YES VR-40221`.
2. To decline, reply `NO VR-40221`.

Small letters work, and so do the marks a phone adds: `yes vr-40221`,
`Yes VR-40221.` and `No, VR-40221` all work. If only one request waits for
you, `YES` or `NO` alone is enough. If the reference has a typing mistake,
the app answers "No request has reference" and decides nothing. Send any other message to see the requests that wait
for you.

If you do not answer in 15 minutes, the backup approver gets the same
request. If you have no backup, you get a reminder instead. The first reply
decides. A reply after that changes nothing.

If the request was made between 10:00 and 17:00, Monday to Saturday, and no
one answers in 30 minutes, the app approves it. Both approvers get a message
that says so. To stop a visitor, reply `NO` before that time.

A request that nobody approves in 48 hours expires. A reply after that gets
"expired", and the visitor must send a new request.

## Guard

You can work from the gate page or from WhatsApp. Both record the same thing,
and the admin page shows which guard recorded each entry and exit.

When a request is approved, every guard gets a WhatsApp message with the
reference, the name, the reason and the person visited. The message has no gate code.
WhatsApp delivers it only if the guard wrote to the app's number in the last
24 hours. The approver who decided gets no copy.

### On the gate page

1. Open `<address>/gate`.
2. Type your gate key. The page asks for it once on each phone. Under the
   lists, the page names the guard whose key it uses.
   - If you lost the key that the admin made for you alone, send `KEY` from
     your phone to the app's WhatsApp number. You get a new key, and the old
     one stops.
   - If you use the shared gate desk key and do not know it, tap "Forgot gate
     key?". The app sends the key to the gate desk WhatsApp. If it does not
     arrive, send `KEY` from the gate desk phone to the app's WhatsApp
     number.
   - On a phone that other people also use, tap Lock at the top when you
     finish. It forgets the key on that phone at once. The gate page also
     locks by itself after 8 hours with no tap or key press.
   - With no connection, the board says so at the top, with the time of its
     last refresh. You cannot check a pass then: use the paper log in
     [university-deployment.md](university-deployment.md).
3. Type the code on the visitor's pass, and tap "Check the pass". Small
   letters and spaces are correct, for example `kt 4821`. For a staff
   member, see "The allow list" below.
4. If the pass is approved, tap "Take a photo of the visitor". The phone
   camera opens. Take the photo of the visitor's face.
5. Make sure that the photo on the screen shows the visitor, then tap Record
   entry. Record entry does not work without a photo. To take the photo
   again, tap "Take the photo again".
6. When the visitor leaves, type the exit code, tap "Check the pass", then
   tap Record exit.
7. Tap Next visitor to clear the screen.

The page shows two lists:

1. Inside now: everyone on campus, the longest first. A yellow row means that
   the visitor entered more than 8 hours ago.
2. Expected: the approved passes that nobody has used yet and that have not
   expired.

A tap on a name only shows the details. It records nothing. The lists refresh
every 30 seconds and after each entry or exit. The badge says Live while the
lists are fresh and Offline after a refresh fails. The gate page has no
download of the visit log. Only the admin page has one.

### On WhatsApp

1. Send `IN` and the entry code, for example `IN KT-4821`.
2. The app asks for a photo of the visitor. Take it in the same chat and send
   it in 10 minutes or less. The photo records the entry.
3. When the visitor leaves, send `OUT` and the exit code, for example
   `OUT RM-0937`.

To look at a pass and record nothing, send only the code or the reference.

The rules for the photo:

1. If the photo comes more than 10 minutes after `IN`, send `IN` again.
2. While you still owe a photo, a new `IN` for another pass is refused, and
   the reply names the visitor whose photo you owe. So a photo can never go
   to the wrong visitor. Send that photo first. To drop it, send `CANCEL`:
   nobody is let in. An `IN` for the same pass again is fine.
3. One photo lets in one person. A second photo on the same `IN` does nothing.
4. Only a guard can send the photo: the `GUARD` number, or a guard on the
   admin page's Guards part.

Both routes need a photo before the visitor goes in. A photo from the gate
page is kept in the app's database, and the admin can see it. A photo sent on
WhatsApp stays in the guard's chat.

### When the gate says no

| The gate says                     | Do this                                                                                    |
|-----------------------------------|--------------------------------------------------------------------------------------------|
| Not approved yet                  | Do not let the visitor in. Ask them to wait                                                |
| Declined                          | Do not let the visitor in                                                                  |
| Pass expired                      | Do not let them in. Ask for a new request                                                  |
| ... is the exit code              | Ask for the entry code                                                                     |
| This pass is closed               | The visit is over. The code is dead                                                        |
| Take a photo of the visitor first | Tap "Take a photo of the visitor". If the page has no photo button, reload the page        |
| Wrong gate key                    | With your own key: send `KEY` from your phone. With the shared key: tap "Forgot gate key?" |

### The allow list

People on the admin page's allow list, such as staff and faculty, do not send
a request. Each one has a 7-digit allow list code.

Use the same code when the person comes in and when the person goes out. The
app decides which one it is. If the person came in during the last 16 hours
and did not go out, the code records an exit. In all other cases, the code
records an entry. A night shift from 22:00 to 06:00 works. A forgotten exit
does not carry over to the next day.

1. The person says their code to you.
2. On WhatsApp, send the code, for example `4569918`. The entry or exit is
   recorded at once, and the reply says which one.
3. On the gate page, tap Staff code at the top. The background turns light
   green, and the phone shows the number keypad. Type the code and tap
   "Record entry or exit", or press Enter. The page shows which one it
   recorded: "Entry recorded" on green, or "Exit recorded" on bright red. It
   also shows the name in large letters, with their tag, such as their
   department. A code typed in the Visitor pass mode works too, and switches
   the page to Staff code.
4. Read the banner. If it says exit and the person is coming in, or the
   opposite, tap "Wrong? Change to entry" or "Wrong? Change to exit" under
   the name. On WhatsApp, send `IN 4569918` or `OUT 4569918`. Within 10
   minutes, this changes the wrong scan, so the log keeps no wrong row.
5. Read the name. If it is not the person in front of you, do not let them
   in, and tell the admin.
6. The page stays in Staff code, with the code box empty, so type the next
   person's code at once. Tap Visitor pass for a visitor: its background is
   light blue.

The same code again within 2 minutes records nothing new. A person on the
blacklist cannot enter, but the code always records their exit.

The person gets a WhatsApp message about each entry, with the time and your
name, but not your number. The reply tells you if that message could not be
sent. An exit sends no message. The admin page shows each entry and exit and
the guard who recorded it.

If the same code comes again within 2 minutes, from you or from another
guard, the reply says "Already recorded" with the first time. Nothing new is
recorded, and no second message is sent. One guard can try 60 codes in a
minute. The gate page uses one of those for each person, so a guard can
take 60 people a minute. After that, the reply says
to wait a minute.

### The blacklist

If the gate page or the WhatsApp reply says "On the blacklist", do not let
the person in, and tell the admin. This also applies to a pass that was
approved before the admin added the number. On the gate page, a banned
visitor in the Expected or Inside now list shows in red, with "On the
blacklist". A banned visitor who is inside can still leave.

## Admin

1. Open `<address>/admin`.
2. Type your admin key. It is different from the gate key.
   - The main admin uses `ADMIN_KEY`. If you do not know it, tap "Forgot
     admin key?". The app sends it to `ADMIN_PHONE` on WhatsApp. If it does
     not arrive, send `KEY` from that phone to the app's WhatsApp number.
   - Another admin added you: use the key they gave you. Or send `KEY` from
     your own WhatsApp to the app's number. The app replies with a new admin
     key of your own, and your old key stops.
3. The menu on the left groups the parts of the page:
   - Daily: Today and Visits.
   - People: Allow list and Blacklist.
   - Setup: Approvers & offices, Guards, Admins and Change log.

   Today opens first. It shows the requests that wait for a decision, the
   visitors inside, the staff today, and the blacklist's blocks in the last
   24 hours. Staff today has one row for each person who came in or went out
   since midnight, and each person still in from a night shift. The "On
   campus" chip lists the people inside now. The "Left" chip lists the people
   who went out. The search box finds a name, code or tag. Tap a number to
   open that list. On a phone, tap Menu
   at the top to open the menu. Under the title, you see who is signed
   in. The address keeps the part that is open, so Refresh and Back
   keep your place.
4. In Visits, tap a tile to show only the requests with that status.
   Waiting means pending, or asked again: sent to the backup, or a reminder
   to the approver.
5. Use the search box to find a name, phone number, reference or the person
   visited.
6. Read the line under each name. It shows the decision and who made it, for
   example "Declined by the backup approver +919876543211". A decision made
   before 5 October 2026 shows no number, and the oldest show no role,
   because the app did not keep them then.
7. Tap a request to see all its details and times, and when its pass ends.
   If the gate page took the photo, a super admin can tap View photo to see
   it.
   Entered and Exited name the guard who recorded them. "Gate desk (shared
   key)" means that someone used the shared `GATE_KEY`.
8. Show more loads the next 50 requests.
9. Use Download logs, at the bottom of the menu, to save the two logs: the
   visit log as a ZIP file, and the staff entry log as a CSV file. See
   "Where the data lives". Only a super admin can download them, because
   they hold every visitor's details and face. Other admins do not see the
   button. The first time, the browser can ask if this site can download
   more than one file. Allow it. If the browser does not save the second
   file, use Download staff entries in Allow list, above Recent entries.

Each list has one button at the top right to add to it, such as Add person
or Add guard. The form opens under the title. Cancel closes it. Under each
list, "How ... works" opens the rules for that list.

The admin page works on a phone and on a computer. On a phone, the menu
opens from the Menu button, the tiles scroll sideways, and each table row
shows as a card.

### Button colors

The buttons have one color for each kind of action, on the admin page and
the gate page. Each button also says what it does, so the color is never
the only sign.

| Color | Means                      | For example                                       |
|-------|----------------------------|---------------------------------------------------|
| Green | Approve, or let someone in | Approve, Record entry, Make super admin           |
| Red   | Delete, decline or ban     | Delete, Decline, Add to the blacklist             |
| Amber | A key, or leave            | New key, Sign out, Lock                           |
| Blue  | Add, change or look        | Add guard, Tag, Change, View photo, Download logs |
| White | Neutral                    | Refresh, Cancel, Next visitor                     |

### How the app knows who you are

The app has no sign-in sessions. Each page keeps your key in the browser on
that device, and sends it with every call. The server finds the person who
owns that key, and the log names that person. So:

1. Each guard and each added admin must use their own key on their own
   device. The log then names them.
2. Anyone who types the shared `GATE_KEY` shows as "Gate desk (shared key)",
   and anyone who types `ADMIN_KEY` shows as the main admin. The app cannot
   tell those people apart.
3. On a shared device, tap Sign out at the bottom of the menu when you
   finish. Otherwise, the next person works under your name. The admin page
   also signs out by itself after 30 minutes with no click or key press, and
   a sign-out in one browser tab signs out the others.

### Approve or decline many requests at once

A super admin can decide many waiting requests, on Today or in Visits. The
main admin is always a super admin. A super admin can make another admin
one, in Admins.

1. Open Today. Or open Visits and tap the Waiting tile.
2. Tick the requests, or tap "Select all waiting on screen". It picks only
   the requests on screen. Tap Show more first to load more of them.
3. Tap Approve or Decline, then confirm in the "Are you sure?" box. One call
   takes 100 requests at most.

Each request is checked on its own, the same way as a `YES` on WhatsApp. The
app skips a request that someone decided meanwhile, one that expired, or one
whose number is on the blacklist. The note then names each skipped request
and why. Each guard gets one WhatsApp message that lists all the approved
visitors, not one message for each. Visits shows "Approved by" and
the admin's name, and the change log keeps a line with every reference.

### Delete something

Each Delete button in Approvers & offices, Allow list, Blacklist, Guards and
Admins opens a box that asks "Are you sure?". Tap Delete to delete, or
Cancel to keep it.

### Change the approvers

1. Open Approvers & offices in the menu.
2. Tap Change on the reason. See an office is not in that table, because each
   office has its own two numbers, in the offices list below the reasons.
3. Type the approver's number, and the backup's number if there is one.
   Write each one with `+` and the country code, like `+919876543210`. The
   backup must be a different person. With no backup, the approver gets a
   reminder instead.
4. In "Approve by itself after (minutes)", type the time for automatic
   approval in working hours. Leave it empty for the default, 30 minutes.
   Type 0 if a person must always decide.
5. Tap Save.

For an office, tap Time on its row to set the same time. A change of time
also moves the open requests that wait for automatic approval.

The change works at once. New requests go to the new numbers. The old numbers
can no longer decide that reason's requests, also the requests already sent
to them. The app sends each open request to the new number at once, so it
does not wait for the reminder: a waiting request to the new approver, and a
request already asked again to the new backup. The same happens when you
delete an office: its open requests go to the approvers for "Other". The
admin change log says how many requests went. While the app uses Meta's test number, also add each new number to
the recipient list in Meta's API Setup page.

Once the app sends from the campus's own WhatsApp number (step 4 of "Before
real use" in [setup.md](setup.md)), there is no recipient list. Every number
on the admin page then works at once: approvers, offices, guards, admins and
the allow list. Nobody needs the Meta page for those changes. Two Meta rules
stay: a plain-text message reaches a person only if they wrote to the app's
number in the last 24 hours, and the business number, the token and the
templates are changed in Meta, not on the admin page.

### Before you make someone an approver

An approver decides who enters the campus, so check each new number:

1. Get the written approval of the head of that office, or of the security
   office, for this person as approver.
2. Phone the person on the number, and make sure that it is their own
   WhatsApp number, not a shared or office phone.
3. Save the number on the admin page.
4. Ask the person to send any message, such as "hi", to the app's WhatsApp
   number. An approver gets the reply "No request is waiting for you." with
   the YES and NO commands. If no reply comes, the number on the admin page
   is wrong. Correct it at once.

The change log keeps who saved each number and when.

### Manage the offices

A visitor who picks the reason See an office then picks an office from a
list. The request goes to that office's own approver, and to its backup if
nobody answers in `ESCALATE_MINUTES`.

1. Open Approvers & offices. The offices list is under the reasons. Tap
   Add office.
2. Type the office's name and the approver's number, with `+` and the
   country code. A backup is a second person, who gets the request when
   nobody answers in `ESCALATE_MINUTES`. Leave the backup empty for an office
   with one person: the approver then gets a reminder instead. You can also
   give a tag, see "Tags on long lists".
3. Tap Add office. Visitors can pick it at once.

To change an office's numbers, delete the office and add it again with the
same name. When you delete an office, its open requests go to the approvers
for "Other". With no offices, the visitor types the
office's name, and the request goes to the approvers for "Other".

### Tags on long lists

The offices list and the allow list can hold hundreds of rows, so each office and
each person can have one tag, such as a building or a department. The two
lists have their own tags.

1. To give a tag when you add a row, tap a tag under the Tag box, or type a
   new one. Leave it empty for no tag. A tag typed in another case, such as
   `physics` for `Physics`, joins the tag in use.
2. To move one row to another tag, tap Tag on that row. An allow list
   person keeps their code.
3. Above each list, the chips show All, each tag with its count, and No tag.
   Tap one to see only those rows. Under All, the rows sit under a heading
   for each tag.
4. The search box finds a name, a number, a code or a tag.
5. To rename a tag for every row at once, tap that tag's chip, then Rename
   this tag. A name that is in use already joins the two tags. An empty name
   removes the tag from those rows.

On the visitor page, the office list shows the offices under their tags. The
offices with no tag come last, under Other offices. Every tag change goes into
the admin change log.

### Manage the allow list

1. Open Allow list in the menu, and tap Add person.
2. Type the person's name and WhatsApp number. You can also give a tag, see
   "Tags on long lists".
3. Tap Add and make a code.
4. Tell the person the 7-digit code that shows. The list also shows it.

Recent entries shows the last 100 entries and the guard who recorded each
one. The staff entries are a log of their own, separate from the visit log.
Download staff entries, above Recent entries, saves all of them as
`staff-entries-<date>.csv`. Download logs in the menu saves this file and the
visit log together. Only a super admin sees these buttons. The date and the time are in separate columns, so a
spreadsheet filter on the date shows one day's entries. Delete takes a person off the list, and
their code stops at once. Their past entries stay until `RETAIN_DAYS` ends.
A number on the blacklist cannot be on the allow list. While the app uses
Meta's test number, also add each number to the recipient list in Meta's API
Setup page.

The entry message needs the template in "The allow list entry template" in
[setup.md](setup.md). Without it, WhatsApp delivers the message only if the
person wrote to the app's number in the last 24 hours.

### Manage the blacklist

A number on the blacklist cannot request a visit, and the gate refuses its
passes, also a pass approved before. Its allow list code stops too. The
visitor page says only this: "This number cannot request a visit. Call the
gate desk." It does not say why.

When you add a number, its waiting requests are declined at once, and
Visits shows "Declined by the blacklist". No approver or automatic
approval can approve them later, and the guards get no "Approved visitor"
message. A pass that was already approved stays approved, but the gate
refuses it.

1. Open Blacklist in the menu, and tap Add number.
2. Type the name and the phone number. The reason is for the admins, and you
   may leave it empty.
3. Tap Add to the blacklist.

You can also open a visit, in Today or Visits, and tap "Blacklist this
number".
The app compares the full number with its country code. A number with no
country code is Indian, so `98765 43210`, `098765 43210` and `+919876543210`
are the same number. Two countries' numbers stay apart, even when their last
10 digits are the same. Delete takes a number off the blacklist.

The blacklist knows only phone numbers. It cannot stop a person who uses
another phone, or who comes as a guest on someone else's request.

Each time the blacklist stops someone, the admin page records it:

1. A request from the visitor page.
2. A pass checked at the gate with its entry code, on the gate page or on
   WhatsApp. A tap on a name in the gate lists is not counted, because the
   person need not be at the gate.
3. An allow list code, on the gate page or on WhatsApp.

Blocked attempts in Blacklist shows the last 100, with the time, the name,
the number, what happened and the guard. For 24 hours after an attempt, a
red alert shows at the top of every part, Blacklist in the menu shows the
count, and Today lists the attempts. The page does not refresh by itself, so tap Refresh to see
new attempts. A page that refreshes by itself would keep the database awake
and use up Neon's free hours.

### Manage the admins

`ADMIN_PHONE` is the main admin. It uses `ADMIN_KEY` and cannot be deleted.
You add the other admins on the admin page.

1. Open Admins in the menu, and tap Add admin.
2. Type the admin's name and WhatsApp number.
3. Tap Add admin and make a key.
4. Give the key that shows to that admin. The page shows it only once. If
   you cannot give it in person, the new admin sends `KEY` from their own
   WhatsApp to the app's number, and gets a key of their own.

Every admin sees and changes everything on the admin page. New key makes a
new key and stops the old one. An added admin who loses their key sends `KEY`
from their phone to the app's WhatsApp number. Nobody can delete themselves.
A guard's number cannot be an admin, and an admin's number cannot be a guard.

A super admin also has a Make super admin and a Remove super admin button
on each other admin's row. Nobody can change their own role. Only a super
admin can make a new key for, delete, or change a super admin, so a regular
admin cannot take a super admin's place.

Change log, in the menu, lists who changed what: each guard, admin,
office, allow list or blacklist entry added or deleted, each approver change,
each new key, and each key sent by "Forgot key?" or `KEY`. It never shows a
key. Download logs saves all of it as `admin-changes.csv`.

Read it when something looks wrong. Anyone who holds an admin's unlocked
phone can send `KEY` and get a new admin key. If a change shows "KEY on
WhatsApp from" a number at a time that person did not use it, delete that
admin, or tap New key, at once.

### Manage the guards

The `GUARD` number is the gate desk. It is always a guard and uses the shared
`GATE_KEY`. You add the other guards on the admin page.

1. Open Guards in the menu, and tap Add guard.
2. Type the guard's name and WhatsApp number. Write the number with `+` and
   the country code, like `+919876543210`.
3. Tap Add guard and make a key.
4. Give the key that shows to that guard. The page shows it only once,
   because the app keeps only a hash (a one-way scramble) of the key.

A guard can then use the gate page with their own key, and `IN`, `OUT` and
the photo from their own WhatsApp number.

1. To give a guard a new key, tap New key. The old key stops at once.
2. To take a guard off, tap Delete, then Delete in the "Are you sure?" box.
   Their key and their WhatsApp commands stop at once. The log keeps their
   name on the visits that they recorded.

The app refuses the gate desk number and every admin's number as a guard. While the
app uses Meta's test number, also add each guard's number to the recipient
list in Meta's API Setup page.

The log names a guard only when that guard uses their own key. Anyone who
knows the shared `GATE_KEY` records as "Gate desk (shared key)". After you
give each guard their own key, change `GATE_KEY` and give the new one only to
the gate desk. A removed guard who knows the shared key can still use it.

## WhatsApp commands

One phone number can be an approver and a guard at the same time, so each
job has its own word.

| You send       | What happens                                                                                               |
|----------------|------------------------------------------------------------------------------------------------------------|
| `VR-40221`     | Shows the pass by its reference. A guard sees no phone. An approver sees only the requests they approve    |
| `KT-4821`      | Shows the pass and the next step for that code                                                             |
| `YES VR-40221` | Approves the request                                                                                       |
| `NO VR-40221`  | Declines the request                                                                                       |
| `IN KT-4821`   | With the entry code: asks for a photo of the visitor                                                       |
| a photo        | Records the entry for the last `IN`                                                                        |
| `OUT RM-0937`  | With the exit code: records the exit                                                                       |
| `4569918`      | From a guard, with an allow list code: records the entry, or the exit after an entry in the last 16 hours  |
| `IN 4569918`   | From a guard: records the entry. Within 10 minutes of a wrong scan, it changes that scan                   |
| `OUT 4569918`  | From a guard: records the exit. Within 10 minutes of a wrong scan, it changes that scan                    |
| `CANCEL`       | Drops the photo you still owe after `IN`. Nobody is let in                                                 |
| `KEY`          | From `GUARD` or `ADMIN_PHONE`: sends back that number's key. From an added guard or admin: makes a new key |
| anything else  | Sends back the requests that wait for you                                                                  |

Any case works, and commas, full stops, `!` and `?` are ignored. A
reference can also be typed as `VR40221`, `VR 40221` or `40221`. A
reference made before 6 October 2026 has four digits, such as `VR-4022`, and
it still works. The app ignores every number that is not an approver of a
reason or an office, a guard or an admin.

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

Use random keys of 20 characters or more. The app refuses a shorter gate key
at start, and keeps the admin page locked with a shorter admin key. To make
a key, run `python -c "import secrets; print(secrets.token_urlsafe(24))"`.

1. Open the service on Render, then Environment.
2. Change `GATE_KEY`, `ADMIN_KEY`, or both. The two keys must be different.
3. Click Save, rebuild, and deploy.
4. Give the new gate key to the gate desk. Each gate page asks for it once.
   Guards with their own key do not need it.

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

### Update the packages

`requirements.txt` holds the exact version of every package, and Render
installs from it. `uv.lock` holds the same versions for `uv`. Keep the two
the same.

1. Change the version numbers in `requirements.txt`.
2. Install them, and make `uv.lock` match. Name each package you changed.

   ```
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   uv lock --upgrade-package flask
   ```

3. Run every check, see "The checks".
4. Ship the change, as above. CI installs from `requirements.txt` on Python
   3.11 and 3.14, so a version that breaks either one shows there.
5. To change the Python on Render, change `PYTHON_VERSION` in `render.yaml`
   and on the service's Environment page, then run every check on that
   version first.

### Database changes

The app builds and changes its tables by itself when it starts.
`core/migrations.py` holds the list `MIGRATIONS`, which is the schema changes in
order. The table
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

To put back an older version, click Rollback next to it on Render. Do
not roll back to a version from before 5 October 2026 (commit `ecf09e0`).
Those versions do not know the status `expired`. The gate and WhatsApp then
fail on every expired pass.

A rollback to a version from before 8 October 2026 (migration 8) still runs.
That version matches the blacklist by the last 10 digits again, and numbers
added after the rollback have no full key. Before you go forward again, run
this in the Neon SQL editor:
`UPDATE blacklist SET number_key = phone_number_key(phone) WHERE number_key IS NULL;`

## The checks

The tests start their own empty Postgres from the `pgserver` package, so they
never touch Neon. Install it once.

```
.venv\Scripts\python.exe -m pip install pgserver
```

The page tests and eslint need Node.js, and ruff is a Python package.
Install them once. `npm ci` installs the exact versions in
`package-lock.json`, the same versions that GitHub uses.

```
npm ci
.venv\Scripts\python.exe -m pip install ruff==0.16.2
```

Then run every check with one command. It runs the three test suites and
both linters, and ends with a list of what passed. Each line must say
"passed".

```
.venv\Scripts\python.exe run_tests.py
```

1. The `tests/test_*.py` files run the whole flow with WhatsApp stubbed out.
   They send no message. Each file covers one topic and starts on an empty
   database, so you can run one file alone. `tests/kit.py` holds what they
   share.
2. `tests/test_concurrency.py` makes many requests and many guards at the same
   moment, and checks that each code is unique and each entry happens once.
   It also adds 20 guards at once, and checks that each guard gets a
   different key, each visit names the guard who let the visitor in, and
   each guard gets one message for each approval.
3. `tests/test_form.js` loads the three pages in a real DOM with jsdom.
4. `ruff` and `eslint` are the linters. Their settings files give the reason
   for each rule that they turn off. The important one is `no-implicit-globals`. The
   pages have no build step, so each button calls a global function from an
   `onclick` attribute. The linters also limit complexity: a Python function
   can have at most 8 branches, and a page function at most 10. If a change
   goes over the limit, split the function into named parts.

To use another Postgres for the tests, set `TEST_DATABASE_URL`. Each test
file deletes every table in that database first, so never point it at the
live database.

## The WhatsApp message list

[whatsapp-messages.md](whatsapp-messages.md) shows every WhatsApp message the
app sends, in each scenario. A tool makes it by running the app with WhatsApp
captured, so it always matches the code. After you change a message, make it
again:

```
.venv\Scripts\python.exe tools\whatsapp_messages.py
```

The tool stops with an error if a message is longer than WhatsApp allows, or
if a message the app sends by itself holds a gate code.

## The README pictures

The README at the repository root shows six pictures of the app. When a
screen changes, take the pictures again. The script starts the app on your
machine with an empty test Postgres, fake settings and five made-up visitors.
It sends no WhatsApp message and does not touch the live database. It drives
Google Chrome, so Chrome must be installed. Install the playwright package
once.

```
.venv\Scripts\python.exe -m pip install pgserver playwright==1.63.0
```

Then run the script. It saves the six pictures in the `pictures` folder, which
git ignores.

```
.venv\Scripts\python.exe tools\screenshots.py
```

Look at each picture. Copy the pictures that changed into the `images` folder
at the repository root, with the same names. If a picture shows something
new, update its alt text in the README.

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

Download logs on the admin page saves the only copy that you control. Save it
before a large change, and on a fixed day each week. Neon can restore the
database to an earlier time, under Backup & Restore in the Neon console. On
the free plan, that window is only 6 hours (the project's "History
retention"). A mistake found the next day cannot be undone there.

Download logs saves two files. The first is `staff-entries-<date>.csv`, the
staff entry log. It has one row for each allow list visit: the date, the
person, their code and number, the entry time and the exit time, and the
guards who recorded them. An entry with no exit in the next 16 hours reads
EXIT NOT RECORDED. An exit with no entry in the 16 hours before reads ENTRY
NOT RECORDED. A person who came in less than 16 hours ago and did not go out
reads Still inside. The second
is the visit log, `visit-log-<date>.zip`. Unzip it first: a file inside a
ZIP does not show its photos. It holds:

1. `visits.html`: open it in a browser. Each visit shows with its gate photo
   beside the details, newest first. It works with no internet.
2. `visits.csv`: one row for each visit, for a spreadsheet.
3. `blocked-attempts.csv`: each time the blacklist stopped someone. The same
   person stopped the same way again within 10 minutes is one row.
4. `admin-changes.csv`: who changed what.
5. `photos/`: one JPEG for each photo taken on the gate page, named by the
   reference, such as `photos/VR-40221.jpg`.
6. `README.txt`: what each file holds.

The files are made for people to read:

1. Each column has a plain heading, such as "Requested" or "Decided by".
2. Times are campus time (`WORK_TIMEZONE`, `Asia/Kolkata` by default), as
   `2026-10-06 16:05`. The heading names the time zone. A spreadsheet reads
   them as dates, so you can sort and filter them.
3. Status is a word, such as Waiting, Approved or Left.
4. "Decided by" names the approver and their number, the admin who decided
   on the admin page, "Approved by itself", or "The blacklist".
5. A number with `+`, such as `+919876543210`, shows as written, not as
   `9.19E+11`.
6. Each CSV starts with a mark that tells Excel the file is UTF-8, so names
   with accents show correctly.
7. An empty cell means "not yet" or "none". A visit that never entered has
   empty Entered and Exited cells.

`visits.csv` has these columns: Reference, Name, Phone, Address, Reason,
Office, Visiting, People with them, Status, Requested, Asked again,
Decided, Decided by, Entered, Entered by, Exited, Exited by, Photo taken and
Photo file. Photo file names the photo in the `photos` folder. It is empty for
a photo sent on WhatsApp, because that photo stays in the guard's chat. The
Visits page in `visits.html` says so too.

A CSV file holds text only, so the photos are separate files in the same ZIP.
A photo written into a CSV cell is about 47,000 characters, and Excel cuts a
cell at 32,767, so the picture breaks. The server sends the ZIP piece by
piece, so a large log does not fill the server's memory. A test with 2,000
photos sent 71 MB and used about 5 MB of memory.

The app deletes each record after `RETAIN_DAYS`, but a downloaded ZIP keeps
its copy. Keep the ZIP files on a locked device, and delete old ones as the
campus's own rules say.

## The free plans

1. Render sleeps after 15 quiet minutes. The first request after that waits
   up to about a minute. The visitor's page still opens at once from the
   phone's copy.
2. While Render sleeps, the timer does not run. Reminders to the backup
   approver, automatic approvals and expiries wait until the app wakes. The
   app wakes when somebody opens a page or sends a WhatsApp message.
3. Neon gives 100 compute hours a month and 0.5 GB. The timer asks the
   database only when a reminder, an approval or an expiry is due, and once
   an hour when nothing is due. The server keeps the gate board, each
   visitor's status and the guard list in memory until something changes,
   so open gate pages and visitor pages do not ask the database. Neon can
   sleep while nothing happens. Look at the compute graph on the Neon
   console to see when it sleeps.
4. Storage, not the references, sets how many visits the app can keep. Each
   gate page photo uses about 30 to 40 KB, and the app keeps it for
   `RETAIN_DAYS`. The 0.5 GB holds roughly 12,000 visits with photos. Look
   at the storage on the Neon console each month. Keep `RETAIN_DAYS`
   multiplied by the visits in one day well under that number. If the
   storage is full, the database can refuse new data, and new requests fail.
5. If the compute hours run out, the app stops until the next month, and the
   uptime check reports `"database":false`.

## How the app behaves

### The background timer

The timer runs inside the server. Each round does four jobs. It approves the
requests that are due for automatic approval, and it asks again about the
requests that nobody answered: the backup approver, or the approver with a
reminder when there is no backup. Then it marks old passes as expired
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
3. The phone also keeps the last settings: the office list and the gate desk
   number. With no signal, the form still shows the offices.
4. The status check stops while the page is hidden. It runs again when the
   page shows, or when the phone comes back online. After failures, it waits
   longer each time, up to 60 seconds.
5. An unchanged status, and an unchanged gate board, cost an empty answer
   (304). The page sends back a tag of what it has, and the server sends
   an empty answer when nothing changed. The gate board refreshes every 30
   seconds, so this saves most of its data.
6. Each script's address holds a hash of its content, so the browser keeps
   each version for a year. The pages are checked on each load.
7. On Render, Cloudflare compresses every answer with Brotli. On a university
   server, turn on gzip or Brotli at the HTTPS proxy, such as nginx.
8. The gate page needs a signal to check a pass. With no signal, the guard
   cannot check any pass, on the page or on WhatsApp.

### Fixed times in the code

| Name            | File                | Value | What it sets                              |
|-----------------|---------------------|-------|-------------------------------------------|
| `PHOTO_MINUTES` | `routes/webhook.py` | 10    | Minutes the guard has to send the photo   |
| `LONG_HOURS`    | `static/gate.js`    | 8     | Hours inside before the row turns yellow  |
| `IDLE_SECONDS`  | `services/timer.py` | 3600  | The longest sleep of the background timer |

### The database connections

On the server, two database connections stay open. A request waits 5 seconds
at most for a connection. A read whose connection breaks runs once more. A
change to the database never runs twice, because its COMMIT can land when
the reply is lost.

### How the work grows

In this table, n is the number of stored visits. k is the number of rows
that an operation returns or changes. s is the number of stored staff scans.
"From memory" means that a repeated read costs no database query until the
app changes the data. The first
read after a change, and every read in the first 2 minutes after the server
starts, goes to the database.

| Work                                | Cost          | How                                        |
|-------------------------------------|---------------|--------------------------------------------|
| Visitor status check, 5 to 30 s     | O(1)          | From memory, after the first query         |
| Look up a pass by its code          | O(log n)      | One query on the code key                  |
| Decide, enter, exit                 | O(log n)      | One UPDATE that returns the new row        |
| Background round, when work is due  | O(log n + k)  | Indexes on status and time                 |
| Gate board, every 30 s              | O(k)          | From memory, after the first query         |
| Blacklist check, for each row       | O(1)          | One shared set of numbers, not copied      |
| Allow list code, guard or admin key | O(1)          | One shared index, not copied               |
| One admin page, first or fiftieth   | O(log n + 50) | Starts after the last row of the last page |
| Admin counts by status              | O(n)          | One pass over an index                     |
| Admin search                        | O(n) at worst | Reads rows until the page is full          |
| CSV export                          | O(n)          | It returns every row                       |
| Allow list or office search         | O(m)          | m people; only 200 rows go on the page     |
| Staff scan, entry or exit           | O(log s)      | One query on the code and time index       |
| Staff today, on each admin refresh  | O(t log t)    | t scans in the last 16 hours, sorted once  |
| Staff today search and chips        | O(p)          | p people today; 25 rows go on the page     |
| Staff entry log CSV                 | O(s log s)    | One pass pairs entries and exits, one sort |

A reference has five digits, so there are 90,000 references. A new request
picks one at random and tries again if it is taken. The free storage fills
long before the references run out, see "The free plans". Admin search reads every row when
the word is rare. A trigram index (`pg_trgm`) can fix that, but the test
database does not have it, and the tests must use the same schema as
production. The retention period keeps n small, so the search stays fast.

Measured on 6 October 2026, with 2,000 blacklisted numbers and 2,000 people
on the allow list: the gate board with 60 expected visitors went from 254 ms
to under 1 millisecond, and an allow list lookup from 8 to 0.2 milliseconds. On the admin
page, one search of 2,000 people went from 742 ms to 49 ms in the test
browser. Before, each blacklist check copied the whole list, every row made
a new date formatter, and the page drew every row. Now the lookups share one
read-only index, the page draws 200 rows with a "Show more" button, and the
search waits for a pause in typing.

Measured on 8 October 2026 with 200,000 visits, 400,000 pass codes and 5,000
blacklisted numbers, with `EXPLAIN ANALYZE` on every query the app runs
often. All but four read an index and take under 1 millisecond:

| Query                    | Time         | Cost       | Note                                   |
|--------------------------|--------------|------------|----------------------------------------|
| Timer: the next due time | 0.2 ms       | O(log n)   | Was up to 45 ms: a full walk of visits |
| Timer: delete old codes  | under 0.1 ms | O(k log n) | Was 33 ms each round, a full scan      |
| Admin counts by status   | 28 ms        | O(n)       | Kept in memory until the next change   |
| Admin search             | 100 ms       | O(n)       | A word inside a field needs `pg_trgm`  |

n is the number of visits and k the number of visits past `RETAIN_DAYS`.
The retention period keeps n near the visits of 90 days.

If you change rows outside the app, for example a restore in the Neon
console, restart the service on Render. The server keeps some reads in
memory, and only its own writes clear them. The timer also clears them
once an hour.

## When something fails

| You see                                             | Do this                                                  |
|-----------------------------------------------------|----------------------------------------------------------|
| The app does not start, and the log names a setting | Set that setting on Render, as the log says              |
| Error 190 in the log                                | The Meta token expired. Make a new permanent token       |
| Error 131030                                        | The number is not on the Meta recipient list. Add it     |
| Error 132001                                        | The template does not exist or is not approved yet       |
| `could not deliver` with error 131047               | The 24-hour window. Make sure the template is in use     |
| `Approval template refused`                         | The template is missing or waits for Meta's review       |
| The reply never changes the page                    | Check the Callback URL and the `messages` subscription   |
| The webhook answers 403                             | `META_APP_SECRET` does not match the Meta app            |
| The gate page says "Wrong gate key"                 | Tap "Forgot gate key?", or send `KEY` from the gate desk |
| The admin page says it is locked                    | Set `ADMIN_KEY`, different from `GATE_KEY`               |
| All visitors get "Too many requests"                | Set `BEHIND_PROXY=true` on Render                        |
| The Tests workflow is red                           | Do not deploy. Read the failed check in the run          |
| The Uptime workflow is red                          | Read "The uptime check" above                            |

Meta reports a lost message later, through the webhook. The app writes each
one to the log as `WhatsApp could not deliver to <number>: error <code>`.

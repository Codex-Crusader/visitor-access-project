# WhatsApp messages

Every message the app sends on WhatsApp, in each scenario. A tool made this page by
running the app with WhatsApp captured, so the words are exactly what people get.
To make it again after a change, run `tools\whatsapp_messages.py`, see
[maintenance.md](maintenance.md). Keys show as `<the key>`.

Approval requests and, once it is approved, the staff entry message go out as Meta
templates, which arrive at any time. Every other message is plain text, which arrives
only if the person wrote to the app's number in the last 24 hours. A reply always
arrives, because the person just wrote.

## A visitor sends a request

To the approver:

```
Campus visit request VR-32689.
New request, waiting for your decision.

Name: Asha Rao
Phone: 9876543210
Address: Karjat
Reason: Event
Visiting: Annual fest
With: Ravi Rao

Reply YES or NO followed by the reference to decide this request.

(template visit_request)
```

## Nobody answers in time: the backup approver is asked

To the backup approver:

```
Campus visit request VR-45883.
Backup approver: no answer from the first approver.

Name: Asha Rao
Phone: 9876543210
Address: Karjat
Reason: Event
Visiting: Annual fest
With: Ravi Rao

Reply YES or NO followed by the reference to decide this request.

(template visit_request)
```

## An office with no backup: its approver gets a reminder

To an office approver:

```
Campus visit request VR-49622.
Reminder: this request still waits for your decision.

Name: Asha Rao
Phone: 9876543210
Address: Karjat
Reason: See an office
Visiting: Accounts
With: Ravi Rao

Reply YES or NO followed by the reference to decide this request.

(template visit_request)
```

## An admin changes the approver: open requests go to the new one

To +919000000077:

```
Campus visit request VR-79178.
New request, waiting for your decision.

Name: Asha Rao
Phone: 9876543210
Address: Karjat
Reason: Delivery
Visiting: Front office
With: Ravi Rao

Reply YES or NO followed by the reference to decide this request.

(template visit_request)
```

## Nobody answers in working hours: the app approves by itself

To the approver:

```
VR-50925 was approved automatically. No one answered within 30 minutes of the request, made in working hours.

VR-50925: Asha Rao, visiting Annual fest (Event)
```

To the backup approver:

```
VR-50925 was approved automatically. No one answered within 30 minutes of the request, made in working hours.

VR-50925: Asha Rao, visiting Annual fest (Event)
```

To the gate desk:

```
Approved visitor on the way. VR-50925: Asha Rao, visiting Annual fest (Event)
With: Ravi Rao

When they arrive, send IN and the entry code on their pass, then a photo of the visitor.
```

## The approver replies YES

The approver sends: `yes vr-32689`

To the gate desk:

```
Approved visitor on the way. VR-32689: Asha Rao, visiting Annual fest (Event)
With: Ravi Rao

When they arrive, send IN and the entry code on their pass, then a photo of the visitor.
```

To the approver:

```
VR-32689 is now approved.

VR-32689: Asha Rao, visiting Annual fest (Event)
```

## A second YES on the same request

The approver sends: `YES VR-32689`

To the approver:

```
VR-32689 was already approved.
```

## The approver replies NO

The approver sends: `No, VR-90911.`

To the approver:

```
VR-90911 is now declined.

VR-90911: Asha Rao, visiting Annual fest (Event)
```

## A reference with a typing mistake

The approver sends: `YES VR-12`

To the approver:

```
No request has reference VR-12. Check the reference in the request message.
```

## An approver decides another reason's request

An office approver sends: `YES VR-45883`

To an office approver:

```
VR-45883 goes to another approver. You cannot decide it.
```

## YES on a request older than the pass time

The approver sends: `YES VR-52985`

To the approver:

```
VR-52985 expired: it was made more than 48 hours ago. The visitor must send a new request.
```

## YES with no reference while several wait

The approver sends: `YES`

To the approver:

```
These requests are waiting for you:

VR-45883: Asha Rao, visiting Annual fest (Event)
VR-79178: Asha Rao, visiting Front office (Delivery)
VR-78344: Neha Joshi, visiting Annual fest (Event)
VR-84015: Karan Mehta, visiting Annual fest (Event)

Reply YES <reference> or NO <reference>.
```

## Any other message from an approver

The approver sends: `hello`

To the approver:

```
These requests are waiting for you:

VR-45883: Asha Rao, visiting Annual fest (Event)
VR-79178: Asha Rao, visiting Front office (Delivery)
VR-78344: Neha Joshi, visiting Annual fest (Event)
VR-84015: Karan Mehta, visiting Annual fest (Event)

Reply YES <reference> or NO <reference>.
```

## YES on a request whose number was just blacklisted

The approver sends: `YES VR-80192`

To the approver:

```
VR-80192 cannot be approved: the number is on the blacklist.
```

## YES with nothing waiting

The approver sends: `YES`

To the approver:

```
No request is waiting for you.

Send a reference like VR-40221 to see that request.
YES <reference> approves. NO <reference> declines. Small letters work too.
```

## A guard looks up a pass by its entry code

A guard sends: `YY-9787`

To a guard:

```
Approved. Reply IN YY-9787, then send a photo of the visitor.

Reference: VR-98884
Name: Asha Rao
Visiting: Annual fest
Reason: Event
With: Ravi Rao
```

## IN with no code

A guard sends: `IN`

To a guard:

```
Add the entry code from the visitor's pass. For example: IN KT-4821.

Send a pass code like KT-4821 to see that pass.
IN <entry code>, then a photo of the visitor, records entry.
OUT <exit code> records exit. Both codes are on the visitor's pass.
A staff member's 7-digit allow list code records their entry, or their exit if they came in within 16 hours.
IN or OUT with a 7-digit allow list code records that one. Within 10 minutes of a wrong scan, it changes that scan.
CANCEL drops the photo you still owe after IN.
KEY sends you your key for the gate page.
```

## IN with the exit code

A guard sends: `IN KX-5959`

To a guard:

```
KX-5959 is the exit code. The entry needs the entry code on the visitor's pass.
```

## IN with the entry code

A guard sends: `in YY-9787`

To a guard:

```
Take a photo of Asha Rao and send it here.
YY-9787 is let in once the photo arrives.
```

## The guard sends the photo

A guard sends: `(a photo)`

To a guard:

```
Inside now. Reply OUT and the exit code on the visitor's pass to record the exit.

Reference: VR-98884
Name: Asha Rao
Visiting: Annual fest
Reason: Event
With: Ravi Rao
Entered: 8 Oct, 12:39
```

## A photo with no IN before it

A guard sends: `(a photo)`

To a guard:

```
No entry is waiting for a photo.
Send IN <entry code>, then the photo within 10 minutes.
```

## IN for a second visitor while a photo is still owed

A guard sends: `IN EV-0084`

To a guard:

```
You still owe the photo of Asha Rao (VR-36618). Send that photo first, so it cannot go to the wrong visitor. To drop it, send CANCEL. Then send IN again.
```

## CANCEL drops the photo still owed

A guard sends: `CANCEL`

To a guard:

```
The photo of Asha Rao (VR-36618) is no longer waited for, and nobody was let in. Send IN and the entry code to start again.
```

## IN again for a visitor inside

A guard sends: `IN YY-9787`

To a guard:

```
Already inside.
```

## OUT with the exit code

A guard sends: `OUT KX-5959`

To a guard:

```
Closed. The visit is over and its codes are finished.

Reference: VR-98884
Entered: 8 Oct, 12:39
Exited: 8 Oct, 12:39
```

## OUT again on a closed pass

A guard sends: `OUT KX-5959`

To a guard:

```
This pass is closed. The visit is over.
```

## IN for a pass not approved yet

A guard sends: `IN <entry code>`

To a guard:

```
Not approved yet. Do not let them in.
```

## IN for an expired pass

A guard sends: `IN <entry code>`

To a guard:

```
This pass expired. Do not let them in. They must send a new request.
```

## IN for a pass whose number is on the blacklist

A guard sends: `IN <entry code>`

To a guard:

```
On the blacklist. Do not let them in. Tell the admin.
```

## A guard sends an allow list code

A guard sends: `3130126`

To the staff member:

```
Campus entry recorded for Dr Anita Rao at 8 Oct, 12:39 by Ravi.

If this was not you, tell the campus admin.
```

To a guard:

```
Entry recorded: Dr Anita Rao, allow list code 3130126, at 8 Oct, 12:39.
Check that this is Dr Anita Rao. A WhatsApp message about this entry was sent to them.
```

## The same code again within 2 minutes

A guard sends: `IN 3130126`

To a guard:

```
Already recorded: Dr Anita Rao entered at 8 Oct, 12:39. Nothing new was recorded or sent.
```

## The same code later that day: the exit

A guard sends: `3130126`

To a guard:

```
Exit recorded: Dr Anita Rao, allow list code 3130126, at 8 Oct, 12:39.
```

## OUT with an allow list code, to correct a wrong scan

A guard sends: `OUT 3130126`

To a guard:

```
Exit recorded: Dr Anita Rao, allow list code 3130126, at 8 Oct, 12:36.
```

## An allow list code nobody has

A guard sends: `1000000`

To a guard:

```
No one on the allow list has the code 1000000. Check the code, or ask the admin.
```

## An allow list code, with the staff_entry template set

A guard sends: `3130126`

To the staff member:

```
Campus entry recorded for Dr Anita Rao at 8 Oct, 12:39 by Ravi.

If this was not you, tell the campus admin.

(template staff_entry)
```

To a guard:

```
Entry recorded: Dr Anita Rao, allow list code 3130126, at 8 Oct, 12:39.
Check that this is Dr Anita Rao. A WhatsApp message about this entry was sent to them.
```

## An allow list code whose number is on the blacklist

A guard sends: `4144093`

To a guard:

```
Mohan: On the blacklist. Do not let them in. Tell the admin.
```

## A staff entry recorded on the gate page

To the staff member:

```
Campus entry recorded for Dr Anita Rao at 8 Oct, 12:39 by Gate desk.

If this was not you, tell the campus admin.
```

## A staff exit recorded on the gate page: no message

The app sends nothing.

## A super admin approves three requests at once

To the gate desk:

```
3 approved visitors on the way:

VR-28374: Neha Joshi, visiting Annual fest (Event), with Ravi Rao
VR-90647: Karan Mehta, visiting Annual fest (Event), with Ravi Rao
VR-13336: Isha Rao, visiting Annual fest (Event), with Ravi Rao

When they arrive, send IN and the entry code on their pass, then a photo of each visitor.
```

## KEY from the gate desk number

The gate desk sends: `KEY`

To the gate desk:

```
The gate key for the visitor access app is:
<the key>

Do not share it outside the people who need it.
```

## KEY from the main admin's number

The main admin sends: `KEY`

To the main admin:

```
The admin key for the visitor access app is:
<the key>

Do not share it outside the people who need it.
```

## KEY from an added guard

A guard sends: `KEY`

To a guard:

```
Your own gate key for the visitor access app is:
<the key>

Your old key no longer works. Do not share this one.
```

## Help for a guard

A guard sends: `hello`

To a guard:

```
Send a pass code like KT-4821 to see that pass.
IN <entry code>, then a photo of the visitor, records entry.
OUT <exit code> records exit. Both codes are on the visitor's pass.
A staff member's 7-digit allow list code records their entry, or their exit if they came in within 16 hours.
IN or OUT with a 7-digit allow list code records that one. Within 10 minutes of a wrong scan, it changes that scan.
CANCEL drops the photo you still owe after IN.
KEY sends you your key for the gate page.
```

## Help for the main admin

The main admin sends: `hello`

To the main admin:

```
KEY sends you your key for the admin page.
```

## A number that is no approver, guard or admin

Someone sends: `hi`

The app sends nothing.

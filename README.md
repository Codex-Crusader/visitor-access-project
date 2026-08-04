# Campus Visitor Access

A parent travelled three hours to visit her son, started the check-in form an hour before she
arrived so she would not be caught out, and still ended up standing in the rain outside the
gate. She got in when somebody inside the university made a phone call. The system had nothing
to do with it.

This repository is a study of why that happens.

**Read the study: <https://codex-crusader.github.io/visitor-access-project/>**

It is my mid-term product ideation submission for Vijaybhoomi University: research,
sensemaking, and information architecture for the campus visitor entry system. I did not design
an interface. The work was to find where the system actually breaks and to show the reasoning
that got me there.

Bhargavaram Krishnapur, August 2026

## The finding

Entry runs through a third-party visitor management system. A visitor fills in six screens at
the gate, then waits for a host to approve the request before a QR pass arrives over WhatsApp.

The form is genuinely irritating, and it is not the problem. Fixing it moves the emotion line
on the journey map from -1 to 0, while the trough stays at -5.

The real failure is one step further on. The approval has no accountable owner, no time bound,
and no failure path. If the person you named does not act, nothing is rejected. The request is
held, then silently cancelled, and you begin again. The guards cannot rescue you either,
because they do not know who the correct approver is: they call a shortlist and hope somebody
picks up. Silence is the failure mode, and silence has no recovery path.

Underneath that sits a modelling problem. The system knows about visitors and it knows about
approvers, but it does not know about the relationship that motivated the visit. The person you
came to see has no standing to let you in.

So the recommendation is a timer. If the first approver has not responded inside an agreed
window, the request reassigns itself to a named fallback, with the visitor doing nothing and
re-entering nothing. It is the one state the current system does not have, and it is already
what the guards improvise over the phone.

## How it was researched

Fieldwork ran from 31 July to 5 August 2026: three interviews, eight valid card sorts, and five
tree tests. All participants are anonymised.

Two things in here are worth more than the conclusion. The tree test and the card sort
contradict each other in one place, and I have kept both results rather than reporting the
flattering one. Task T4 killed a structural pivot I had been confident about, and task T8
failed outright for every participant in the same way. The study says so, and says what I would
do differently next time.

## What is in the repository

- `index.html`, the entire study as one scrolling page
- `style.css`, written from scratch
- `images/`, the empathy map, the journey map, artefact screenshots, and session photographs

## Running it locally

Nothing to install and nothing to build. Open `index.html` in any browser. No JavaScript, no
frameworks, no dependencies.

## Publishing

The live site keeps itself current. Every push to `main` runs `.github/workflows/deploy.yml`,
which uploads the repository root as a Pages artefact and deploys it. There is no build step and
no `gh-pages` branch, so the commit history stays clean.

Setting this up on a fresh repository:

1. Make the repository public. Private repositories do not serve Pages on a free account.
2. Push everything, `.github/` included, to the repository root.
3. Under Settings, then Pages, set Source to *GitHub Actions*. The first run fails if Pages has
   never been enabled on that repository. Enable it, then re-run the workflow.
4. Give it a minute, then open the URL on a phone and confirm every image loads. Pages is case
   sensitive and your laptop almost certainly is not, so `Journey-Map.png` and `journey-map.png`
   are two different files once they are on the server.

## A note on the screenshots

The six phone screens in the artefact analysis are captures of the live third-party system,
included as evidence of what exists today. They are not proposals, and nothing in this project
is a design for a replacement interface.

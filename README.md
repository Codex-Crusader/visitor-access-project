<div align="center">

# Campus Visitor Access

> **Written up in full:
** [codex-crusader.github.io/projects/campus-visitor-access/](https://codex-crusader.github.io/projects/campus-visitor-access/)
> covers the problem, the architecture, the results and what it deliberately does not do.

> **Run the app:** [setup](application/docs/setup.md) · [maintenance](application/docs/maintenance.md) · [safety](application/docs/safety.md)

**A product ideation study of the visitor entry system at Vijaybhoomi University, from research to a tested, working
prototype**

[![Read the study](https://img.shields.io/badge/read_the_study-live_site-2ea44f?style=for-the-badge&logo=githubpages&logoColor=white)](https://codex-crusader.github.io/visitor-access-project/)
[![Try the demo](https://img.shields.io/badge/try_the_demo-v2_app-c0231e?style=for-the-badge&logo=html5&logoColor=white)](https://codex-crusader.github.io/visitor-access-project/demo/)
[![Prototype](https://img.shields.io/badge/prototype-figma-a259ff?style=for-the-badge&logo=figma&logoColor=white)](https://www.figma.com/design/h8PuevXEBAWSfShzmBR5ba/Campus-Visitor-Access?node-id=0-1)
[![Deploy status](https://img.shields.io/github/actions/workflow/status/Codex-Crusader/visitor-access-project/deploy.yml?branch=main&style=for-the-badge&label=pages%20deploy&logo=githubactions&logoColor=white)](https://github.com/Codex-Crusader/visitor-access-project/actions/workflows/deploy.yml)

![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=flat-square&logo=html5&logoColor=white)
![CSS](https://img.shields.io/badge/CSS-1572B6?style=flat-square&logo=css&logoColor=white)
![JavaScript: demo only](https://img.shields.io/badge/JavaScript-demo_only-lightgrey?style=flat-square)
![Build step: none](https://img.shields.io/badge/build_step-none-brightgreen?style=flat-square)

![Interviews](https://img.shields.io/badge/interviews-3-6f42c1?style=flat-square)
![Card sorts](https://img.shields.io/badge/valid_card_sorts-8-6f42c1?style=flat-square)
![Tree tests](https://img.shields.io/badge/tree_tests-5-6f42c1?style=flat-square)
![Wireframes](https://img.shields.io/badge/wireframes-16-6f42c1?style=flat-square)
![Usability tests](https://img.shields.io/badge/usability_tests-8-6f42c1?style=flat-square)
![Participants anonymised](https://img.shields.io/badge/participants-anonymised-0969da?style=flat-square)

</div>

A parent drove three hours to visit her son. She started the check-in form an hour before she
arrived, so that she did not have to wait. She still stood in the rain outside the gate. She got
in when somebody inside the university made a phone call. The system did nothing to help her.

This repository studies why that happens, and proposes a fix. It covers research, information
architecture and prioritization, then design, then a usability test with eight people, then a
working app rebuilt from the test results.

Bhargavaram Krishnapur, 2026

## The finding

Entry runs through a visitor management system from an outside company. A visitor fills in six
screens at the gate, waits for someone to approve the request, and then gets a QR pass on
WhatsApp.

The form is annoying, but it is not the problem. A better form moves one step of the journey map
from -1 to 0. The lowest point stays at -5.

> [!IMPORTANT]
> The approval step has no owner, no time limit, and no failure path. If the person you named
> does not act, nothing is rejected. The system holds the request, then cancels it without
> telling you, and you start again.

So the recommendation is a timer. If the first approver does not answer in an agreed time, the
request moves to a named backup by itself. The visitor types nothing again. The guards already do
the same thing by phone.

## What testing found

Eight people tried the Figma prototype on 16 and 17 September 2026. They reported 97% of tasks as
done. But only 44% of their answers showed that they understood the screen. Five of eight thought
that a sent request was already approved. Only one of eight found how to add a second visitor.

The app fixes these problems. The waiting screen now opens with "Not approved yet". Every status
screen carries a "Call gate desk" button.

## The app

The working app lives in [`application/`](application/). A visitor fills in the form. The server
sends the details to an approver on WhatsApp. The approver replies `YES` or `NO`. The visitor sees
the decision on the same page a few seconds later. At the gate, a guard checks the entry code on the
pass, takes a photo of the visitor and records the entry. On the way out, the pass shows a new exit
code. After the exit, neither code works. Staff and faculty on the allow list use a 7-digit code:
one scan records the entry, the next one the exit, and each entry sends them a WhatsApp message. The admin page lists every request, and keeps
the offices, the allow list, the blacklist, and the two logs to download.

The pictures below come from the working app, with made-up visitors. The demo has only the visitor
screens, with fixed codes and no server, so some details are different.

<div align="center">

|                                    Home                                    |                                                Request a visit                                                 |                                                   Waiting on the approver                                                   |
|:--------------------------------------------------------------------------:|:--------------------------------------------------------------------------------------------------------------:|:---------------------------------------------------------------------------------------------------------------------------:|
| <img src="images/app-01-home.png" alt="The five section menu" width="250"> | <img src="images/app-02-form.png" alt="Reason chips, the office picked from a list, and one guest" width="250"> | <img src="images/app-03-waiting.png" alt="Not approved yet, with a tracker and the latest time the request is asked again" width="250"> |

| Approved, with the pass | The gate desk | A staff code at the gate |
|:---:|:---:|:---:|
| <img src="images/app-04-pass.png" alt="An entry pass with its entry code" width="250"> | <img src="images/app-05-gate.png" alt="The guard types the entry code and sees Let them in, the visitor's name large, and the photo button before Record entry" width="250"> | <img src="images/app-07-gate-staff.png" alt="In Staff code mode one scan of a 7-digit code records an entry, or an exit on dark gray, with the name and tag large and a button to change a wrong scan" width="250"> |

| The admin page: Today |
|:---:|
| <img src="images/app-06-admin.png" alt="The admin page's Today view: a side menu, counts of what needs action, the waiting requests with bulk approval, the staff on campus or gone with a search box, and recent blocks" width="760"> |

| The allow list and the staff entry log |
|:---:|
| <img src="images/app-08-admin-allow.png" alt="The allow list grouped by tag, each person's 7-digit code, and the recent staff entries and exits with a download button" width="760"> |

| A new approver, and what became of the open requests |
|:---:|
| <img src="images/app-09-admin-approvers.png" alt="After a change of approver, an amber note says one open request went to the new approver and one was not sent, and tells the admin what to do. Below it, each reason's approver, backup and time to approve by itself, and the rule that the backup gets half of that time" width="760"> |

</div>

The waiting screen is the whole recommendation in one picture. It names who holds the request and
states the latest minute the request is asked again: of the backup approver, or as a reminder to
the approver when there is no backup.
[`application/docs/setup.md`](application/docs/setup.md) covers the settings and the setup.
[`application/docs/maintenance.md`](application/docs/maintenance.md) covers the WhatsApp commands
and daily use.

## How it was done

| Phase        | Method                                            | What it produced                                      |
|:-------------|:--------------------------------------------------|:------------------------------------------------------|
| Research     | Interviews: 1 visitor, 2 gate staff               | Persona, empathy map, journey map, core pain point    |
| Structure    | Card sort (8 valid) and tree test (5)             | A six-section menu, changed to five after testing     |
| Priorities   | MoSCoW and a DFV matrix                           | Four must-have features                               |
| Design       | Wireframes, heuristic inspection, prototype       | 16 screens, 3 heuristic fixes, a clickable Figma flow |
| Testing      | Unmoderated usability test (8)                    | 97% reported success against 44% real understanding   |
| Redesign     | Changes from the test, rebuilt in HTML            | A working app, embedded on the site                   |
| Benchmarking | Written comparison with three classmates' studies | Four answers to the same problem                      |

Fieldwork ran from 31 July to 5 August 2026. The usability test ran on 16 and 17 September 2026.
All participants are anonymous. The classmates are named only by their project topic.

The [study site](https://codex-crusader.github.io/visitor-access-project/) holds every phase in
order, with the evidence behind each change.

## What is in the repository

| Path                           | What it is                                                     |
|:-------------------------------|:---------------------------------------------------------------|
| `index.html`                   | The entire study as one scrolling page                         |
| `style.css`                    | The stylesheet, written from scratch                           |
| `demo/index.html`              | The v2 app as one file, with no outside files or libraries     |
| `application/`                 | The Flask app, the WhatsApp approval flow and the gate desk    |
| `images/`                      | Current-system screenshots, maps, tree test sheets, wireframes |
| `.github/workflows/deploy.yml` | Publishes the site to GitHub Pages on every push to `main`     |

> [!NOTE]
> The six phone screens in the problem section are captures of the live system from the outside
> company. They are evidence of what exists today, not a proposal.

## Running it locally

Clone the repository and open `index.html` in a browser. The study site has no build step. Only
the embedded Figma prototype needs an internet connection.

The demo clock runs fast: one minute passes about every half second. Press `d` to decline the
request, `t` to skip 10 minutes, or `r` to start again. These keys do nothing while you type in
a field.

The Flask app is a separate program with its own setup. See
[`application/docs/setup.md`](application/docs/setup.md).

## Publishing

Every push to `main` runs [`deploy.yml`](.github/workflows/deploy.yml). It uploads the repository
root as a Pages artifact. There is no build step and no `gh-pages` branch. On a new repository,
make it public first, because a free account does not serve Pages from a private repository. Then
set Source to **GitHub Actions** under Settings, then Pages, before the first push.

> [!WARNING]
> If Pages was never enabled, the first workflow run fails, because the default token cannot
> create the Pages site. Pages is also case sensitive while your laptop is probably not:
> `Journey-Map.png` and `journey-map.png` are two different files on the server.

## License

Copyright © 2026 Bhargavaram Krishnapur. All rights reserved. See [`LICENSE`](LICENSE). You need
written permission to use, copy or change any part of this repository. The university name and
logo, and the screenshots of other products, belong to their owners.

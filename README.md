<div align="center">

# Campus Visitor Access

> **Written up in full:** [codex-crusader.github.io/projects/campus-visitor-access/](https://codex-crusader.github.io/projects/campus-visitor-access/) covers the problem, the architecture, the results and what it deliberately does not do.

**An end-to-end product ideation study of the visitor entry system at Vijaybhoomi University**

[![Read the study](https://img.shields.io/badge/read_the_study-live_site-2ea44f?style=for-the-badge&logo=githubpages&logoColor=white)](https://codex-crusader.github.io/visitor-access-project/)
[![Deploy status](https://img.shields.io/github/actions/workflow/status/Codex-Crusader/visitor-access-project/deploy.yml?branch=main&style=for-the-badge&label=pages%20deploy&logo=githubactions&logoColor=white)](https://github.com/Codex-Crusader/visitor-access-project/actions/workflows/deploy.yml)

![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=flat-square&logo=html5&logoColor=white)
![CSS](https://img.shields.io/badge/CSS-1572B6?style=flat-square&logo=css&logoColor=white)
![JavaScript: none](https://img.shields.io/badge/JavaScript-none-lightgrey?style=flat-square)
![Dependencies: 0](https://img.shields.io/badge/dependencies-0-brightgreen?style=flat-square)
![Build step: none](https://img.shields.io/badge/build_step-none-brightgreen?style=flat-square)

![Interviews](https://img.shields.io/badge/interviews-3-6f42c1?style=flat-square)
![Card sorts](https://img.shields.io/badge/valid_card_sorts-8-6f42c1?style=flat-square)
![Tree tests](https://img.shields.io/badge/tree_tests-5-6f42c1?style=flat-square)
![Fieldwork](https://img.shields.io/badge/fieldwork-31_Jul_to_5_Aug_2026-0969da?style=flat-square)
![Participants anonymised](https://img.shields.io/badge/participants-anonymised-0969da?style=flat-square)

</div>

A parent travelled three hours to visit her son, started the check-in form an hour before she
arrived so she would not be caught out, and still ended up standing in the rain outside the
gate. She got in when somebody inside the university made a phone call. The system had nothing
to do with it.

This repository is a study of why that happens. It is my mid-term product ideation submission:
research, sensemaking, and information architecture. I did not design an interface. The work was
to find where the system actually breaks, and to show the reasoning that got me there.

Bhargavaram Krishnapur, August 2026

## The finding

Entry runs through a third-party visitor management system. A visitor fills in six screens at
the gate, then waits for a host to approve the request before a QR pass arrives over WhatsApp.

The form is genuinely irritating, and it is not the problem. Fixing it moves the emotion line on
the journey map from -1 to 0, while the trough stays at -5.

> [!IMPORTANT]
> The approval step has no accountable owner, no time bound, and no failure path. If the person
> you named does not act, nothing is rejected. The request is held, then silently cancelled, and
> you begin again.

The guards cannot rescue you either, because they do not know who the correct approver is. They
call a shortlist and hope somebody picks up. Silence is the failure mode, and silence has no
recovery path.

Underneath that sits a modelling problem. The system knows about visitors and it knows about
approvers, but it does not know about the relationship that motivated the visit. The person you
came to see has no standing to let you in.

So the recommendation is a timer. If the first approver has not responded inside an agreed
window, the request reassigns itself to a named fallback, with the visitor doing nothing and
re-entering nothing. It is the one state the current system does not have, and it is already what
the guards improvise over the phone.

## How it was researched

| Method | Sample | What it produced |
| :--- | :--- | :--- |
| Semi-structured interviews | 1 visitor, 2 gate staff | The persona, the empathy map, the journey map |
| Open card sort | 8 valid sorts of 20 items | The first information architecture, six nodes |
| Tree test | 5 participants | The revision to five nodes, and two useful failures |

Fieldwork ran from 31 July to 5 August 2026. All participants are anonymised.

Two things in here are worth more than the conclusion. The tree test and the card sort
contradict each other in one place, and I have kept both results rather than reporting the
flattering one. Task T4 killed a structural pivot I had been confident about, and task T8 failed
outright for every participant in the same way. The study says so, and says what I would do
differently next time.

## Read it by section

| | Section | |
| :--- | :--- | :--- |
| 01 | [Problem space](https://codex-crusader.github.io/visitor-access-project/#problem) | Four conditions that make the system fragile at the gate |
| 02 | [Method](https://codex-crusader.github.io/visitor-access-project/#method) | Who was studied, and how |
| 03 | [Persona](https://codex-crusader.github.io/visitor-access-project/#persona) | The four assumptions that broke |
| 04 | [Maps](https://codex-crusader.github.io/visitor-access-project/#maps) | Empathy map and journey map |
| 05 | [Pain point](https://codex-crusader.github.io/visitor-access-project/#pain) | Located at the lowest dip, triangulated three ways |
| 06 | [Stories](https://codex-crusader.github.io/visitor-access-project/#stories) | Five user stories, each traced to a stage |
| 07 | [Card sort](https://codex-crusader.github.io/visitor-access-project/#cardsort) | Twenty items, eight valid sorts |
| 08 | [Tree test](https://codex-crusader.github.io/visitor-access-project/#treetest) | Where the structure broke |
| 09 | [MoSCoW](https://codex-crusader.github.io/visitor-access-project/#moscow) | Four Must-Haves, no more |
| 10 | [DFV](https://codex-crusader.github.io/visitor-access-project/#dfv) | Desirability, feasibility, viability |

## What is in the repository

| Path | What it is |
| :--- | :--- |
| `index.html` | The entire study as one scrolling page |
| `style.css` | The stylesheet, written from scratch |
| `images/` | Empathy map, journey map, artefact screenshots, session photographs |
| `.github/workflows/deploy.yml` | Publishes the site to GitHub Pages on every push to `main` |

## Running it locally

Nothing to install and nothing to build. Open `index.html` in any browser.

```bash
git clone https://github.com/Codex-Crusader/visitor-access-project.git
cd visitor-access-project
start index.html      # Windows
open index.html       # macOS
```

## Publishing

The live site keeps itself current. Every push to `main` runs
[`deploy.yml`](.github/workflows/deploy.yml), which uploads the repository root as a Pages
artefact and deploys it. There is no build step and no `gh-pages` branch, so nothing writes
commits back into the history.

Setting this up on a fresh repository:

1. Make the repository public. Private repositories do not serve Pages on a free account.
2. Push everything, `.github/` included, to the repository root.
3. Under Settings, then Pages, set Source to **GitHub Actions**.
4. Give it a minute, then open the URL on a phone and confirm every image loads.

> [!WARNING]
> The first workflow run fails if Pages has never been enabled on the repository, because the
> default token cannot create the Pages site itself. Enable it, then re-run the workflow.

> [!TIP]
> GitHub Pages is case sensitive and your laptop almost certainly is not. `Journey-Map.png` and
> `journey-map.png` are two different files once they are on the server, so a page that looks
> perfect locally can arrive with broken images.

## A note on the screenshots

> [!NOTE]
> The six phone screens in the artefact analysis are captures of the live third-party system,
> included as evidence of what exists today. They are not proposals, and nothing in this project
> is a design for a replacement interface.

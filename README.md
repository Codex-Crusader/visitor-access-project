<div align="center">

# Campus Visitor Access

> **Written up in full:** [codex-crusader.github.io/projects/campus-visitor-access/](https://codex-crusader.github.io/projects/campus-visitor-access/) covers the problem, the architecture, the results and what it deliberately does not do.

**A product ideation study of the visitor entry system at Vijaybhoomi University, from research to a tested, working prototype**

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
architecture and prioritization. Then it covers design: wireframes, a heuristic inspection, and a
clickable prototype in Figma. Last, it covers a usability test with eight people and a working
v2 app, rebuilt from the test results.

Bhargavaram Krishnapur, 2026

## The finding

Entry runs through a visitor management system from an outside company. A visitor fills in six
screens at the gate. Then the visitor waits for someone to approve the request. After approval,
a QR pass arrives on WhatsApp.

The form is annoying, but it is not the problem. A better form moves one step of the journey map
from -1 to 0. The lowest point stays at -5.

> [!IMPORTANT]
> The approval step has no owner, no time limit, and no failure path. If the person you named
> does not act, nothing is rejected. The system holds the request, then cancels it without
> telling you, and you start again.

So the recommendation is a timer. If the first approver does not answer in an agreed time, the
request moves to a named backup by itself. The visitor types nothing again. The current system
has no such step. The guards already do the same thing by phone.

## What testing found

Eight people tried the Figma prototype on 16 and 17 September 2026. They reported 97% of tasks as
done. But only 44% of their answers showed that they understood the screen. Five of eight thought
that a sent request was already approved. Only one of eight found how to add a second visitor.

The v2 app fixes these problems. The waiting screen now starts with "Not approved yet". "Add a
visitor" is a button on the status screen. Every status screen has a "Call gate desk"
button.

## How it was done

| Phase | Method | What it produced |
| :--- | :--- | :--- |
| Research | Interviews: 1 visitor, 2 gate staff | Persona, empathy map, journey map, core pain point |
| Structure | Card sort (8 valid) and tree test (5) | A six-section menu, changed to five after testing |
| Priorities | MoSCoW and a DFV matrix | Four must-have features |
| Design | Wireframes, heuristic inspection, prototype | 16 screens, 3 heuristic fixes, a clickable Figma flow |
| Testing | Unmoderated usability test (8) | 97% reported success against 44% real understanding |
| Redesign | Changes from the test, rebuilt in HTML | A working v2 app, embedded on the site |
| Benchmarking | Written comparison with three classmates' studies | Four answers to the same problem |

Fieldwork ran from 31 July to 5 August 2026. The usability test ran on 16 and 17 September 2026.
All participants are anonymous. The classmates are named only by their project topic.

## Read it by section

| Section | |
| :--- | :--- |
| [Summary](https://codex-crusader.github.io/visitor-access-project/#summary) | The whole study in one minute |
| [Problem](https://codex-crusader.github.io/visitor-access-project/#problem) | The current system, screen by screen |
| [Research](https://codex-crusader.github.io/visitor-access-project/#persona) | The persona, and her day step by step |
| [Maps](https://codex-crusader.github.io/visitor-access-project/#maps) | Empathy map, journey map, and the core pain point |
| [Card sort](https://codex-crusader.github.io/visitor-access-project/#cardsort) | How people group the features |
| [Tree test](https://codex-crusader.github.io/visitor-access-project/#treetest) | Where the menu broke, and what changed |
| [Priorities](https://codex-crusader.github.io/visitor-access-project/#moscow) | Four must-haves, and the close call |
| [Design](https://codex-crusader.github.io/visitor-access-project/#design) | Wireframes, heuristic inspection, Figma prototype |
| [Testing](https://codex-crusader.github.io/visitor-access-project/#testing) | What happened when eight people tried it |
| [Changes](https://codex-crusader.github.io/visitor-access-project/#changes) | Before and after, with the evidence for each change |
| [Demo](https://codex-crusader.github.io/visitor-access-project/#demo) | The working v2 app |
| [Peers](https://codex-crusader.github.io/visitor-access-project/#peers) | How three other studies answered the same problem |
| [Reflection](https://codex-crusader.github.io/visitor-access-project/#close) | What I will do differently |

## What is in the repository

| Path | What it is |
| :--- | :--- |
| `index.html` | The entire study as one scrolling page |
| `style.css` | The stylesheet, written from scratch |
| `demo/index.html` | The v2 app. One file, with no outside files or libraries |
| `images/` | Current-system screenshots, maps, tree test sheets, wireframes, before and after pairs |
| `.github/workflows/deploy.yml` | Publishes the site to GitHub Pages on every push to `main` |

## Running it locally

You do not install or build anything. Open `index.html` in a browser. The embedded Figma prototype
needs an internet connection. Everything else works offline, the demo included.

```bash
git clone https://github.com/Codex-Crusader/visitor-access-project.git
cd visitor-access-project
start index.html      # Windows
open index.html       # macOS
```

The demo clock runs fast: one minute passes about every half second. On a keyboard, press `d` to
decline the request, `t` to skip 10 minutes, or `r` to start again. These keys do nothing while
you type in a field.

## Publishing

Every push to `main` runs [`deploy.yml`](.github/workflows/deploy.yml). It uploads the repository
root as a Pages artifact and deploys it. There is no build step and no `gh-pages` branch.

To set this up on a new repository:

1. Make the repository public. Private repositories do not serve Pages on a free account.
2. Push everything, `.github/` included, to the repository root.
3. Under Settings, then Pages, set Source to **GitHub Actions**.
4. Wait a minute. Then open the URL on a phone and make sure that every image loads.

> [!WARNING]
> If Pages was never enabled on the repository, the first workflow run fails. The default token
> cannot create the Pages site itself. Enable Pages, then run the workflow again.

> [!TIP]
> GitHub Pages is case sensitive, and your laptop is probably not. On the server,
> `Journey-Map.png` and `journey-map.png` are two different files.

## A note on the screenshots

> [!NOTE]
> The six phone screens in the problem section are captures of the live system from the outside
> company. They are evidence of what exists today. The proposed design is the gray wireframes, the
> Figma prototype, and the v2 demo.

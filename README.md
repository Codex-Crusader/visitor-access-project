<div align="center">

# Campus Visitor Access

> **Written up in full:** [codex-crusader.github.io/projects/campus-visitor-access/](https://codex-crusader.github.io/projects/campus-visitor-access/) covers the problem, the architecture, the results and what it deliberately does not do.

**A product ideation study of the visitor entry system at Vijaybhoomi University, from research to a clickable prototype**

[![Read the study](https://img.shields.io/badge/read_the_study-live_site-2ea44f?style=for-the-badge&logo=githubpages&logoColor=white)](https://codex-crusader.github.io/visitor-access-project/)
[![Prototype](https://img.shields.io/badge/prototype-figma-a259ff?style=for-the-badge&logo=figma&logoColor=white)](https://www.figma.com/design/h8PuevXEBAWSfShzmBR5ba/Campus-Visitor-Access?node-id=0-1)
[![Deploy status](https://img.shields.io/github/actions/workflow/status/Codex-Crusader/visitor-access-project/deploy.yml?branch=main&style=for-the-badge&label=pages%20deploy&logo=githubactions&logoColor=white)](https://github.com/Codex-Crusader/visitor-access-project/actions/workflows/deploy.yml)

![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=flat-square&logo=html5&logoColor=white)
![CSS](https://img.shields.io/badge/CSS-1572B6?style=flat-square&logo=css&logoColor=white)
![JavaScript: none of its own](https://img.shields.io/badge/JavaScript-none_of_its_own-lightgrey?style=flat-square)
![Build step: none](https://img.shields.io/badge/build_step-none-brightgreen?style=flat-square)

![Interviews](https://img.shields.io/badge/interviews-3-6f42c1?style=flat-square)
![Card sorts](https://img.shields.io/badge/valid_card_sorts-8-6f42c1?style=flat-square)
![Tree tests](https://img.shields.io/badge/tree_tests-5-6f42c1?style=flat-square)
![Wireframes](https://img.shields.io/badge/wireframes-16-6f42c1?style=flat-square)
![Participants anonymised](https://img.shields.io/badge/participants-anonymised-0969da?style=flat-square)

</div>

A parent travelled three hours to visit her son, started the check-in form an hour before she
arrived so she would not be caught out, and still ended up standing in the rain outside the
gate. She got in when somebody inside the university made a phone call. The system had nothing
to do with it.

This repository is a study of why that happens, and a proposed fix. It covers research,
information architecture, prioritisation, and then design: low-fidelity wireframes, a heuristic
inspection, and a clickable prototype in Figma.

Bhargavaram Krishnapur, 2026

## The finding

Entry runs through a third-party visitor management system. A visitor fills in six screens at
the gate, then waits for someone to approve the request before a QR pass arrives over WhatsApp.

The form is irritating, and it is not the problem. Fixing it moves the emotion line on the
journey map from -1 to 0, while the low point stays at -5.

> [!IMPORTANT]
> The approval step has no owner, no time limit, and no failure path. If the person you named
> does not act, nothing is rejected. The request is held, then silently cancelled, and you begin
> again.

So the recommendation is a timer. If the first approver has not responded inside an agreed
window, the request moves to a named backup by itself, and the visitor re-enters nothing. It is
the one state the current system does not have, and it is already what the guards improvise over
the phone.

## How it was done

| Phase | Method | What it produced |
| :--- | :--- | :--- |
| Research | Interviews: 1 visitor, 2 gate staff | Persona, empathy map, journey map, core pain point |
| Structure | Card sort (8 valid) and tree test (5) | A six-section menu, revised to five after testing |
| Priorities | MoSCoW and a DFV matrix | Four must-have features |
| Design | Wireframes, heuristic inspection, prototype | 16 screens, 3 heuristic fixes, a clickable Figma flow |

Fieldwork ran from 31 July to 5 August 2026. All participants are anonymised.

## Read it by section

| Section | |
| :--- | :--- |
| [Summary](https://codex-crusader.github.io/visitor-access-project/#summary) | The whole study in one minute |
| [Problem](https://codex-crusader.github.io/visitor-access-project/#problem) | The current system, screen by screen |
| [Research](https://codex-crusader.github.io/visitor-access-project/#persona) | What I assumed, what I found, the pain point |
| [Card sort](https://codex-crusader.github.io/visitor-access-project/#cardsort) | How people group the features |
| [Tree test](https://codex-crusader.github.io/visitor-access-project/#treetest) | Where the menu broke, and what changed |
| [Priorities](https://codex-crusader.github.io/visitor-access-project/#moscow) | Four must-haves, and the close call |
| [Design](https://codex-crusader.github.io/visitor-access-project/#design) | Wireframes, heuristic inspection, prototype |
| [Reflection](https://codex-crusader.github.io/visitor-access-project/#close) | What I would do differently |

## What is in the repository

| Path | What it is |
| :--- | :--- |
| `index.html` | The entire study as one scrolling page |
| `style.css` | The stylesheet, written from scratch |
| `images/` | Current-system screenshots, maps, tree test sheets, wireframes |
| `.github/workflows/deploy.yml` | Publishes the site to GitHub Pages on every push to `main` |

## Running it locally

Nothing to install and nothing to build. Open `index.html` in any browser. The embedded Figma
prototype needs a connection; everything else works offline.

```bash
git clone https://github.com/Codex-Crusader/visitor-access-project.git
cd visitor-access-project
start index.html      # Windows
open index.html       # macOS
```

## Publishing

Every push to `main` runs [`deploy.yml`](.github/workflows/deploy.yml), which uploads the
repository root as a Pages artefact and deploys it. There is no build step and no `gh-pages`
branch.

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
> `journey-map.png` are two different files once they are on the server.

## A note on the screenshots

> [!NOTE]
> The six phone screens in the problem section are captures of the live third-party system,
> included as evidence of what exists today. The proposed design is the grayscale wireframes in
> the design section and the Figma prototype.

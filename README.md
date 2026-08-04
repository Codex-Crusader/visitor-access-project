# Campus Visitor Access

An end-to-end product ideation study of the visitor entry system at Vijaybhoomi University.
Research, sensemaking and information architecture. Mid-term examination submission.

**Bhargavaram Krishnapur**, August 2026

## Contents

- `index.html` — the full study as a single scrolling page
- `style.css` — stylesheet, written from scratch
- `images/` — empathy map, journey map, artefact screenshots, session photographs

## Build

None. Open `index.html` in any browser. No JavaScript, no frameworks, no build step.

## Publishing to GitHub Pages

Live at <https://codex-crusader.github.io/visitor-access-project/>

Publishing is automatic. Every push to `main` runs `.github/workflows/deploy.yml`, which
uploads the repository root as a Pages artefact and deploys it. There is nothing to build
and no `gh-pages` branch. Settings, then Pages, then Source is set to *GitHub Actions*.

To publish this study from a fresh repository:

1. Create a **public** repository. Private repositories do not serve Pages on a free account.
2. Push everything, including `.github/`, to the repository root.
3. Settings, then Pages, then Source: *GitHub Actions*. The first run fails if Pages has
   never been enabled on the repository; enable it, then re-run the workflow.
4. Wait about a minute. The URL will be `https://<username>.github.io/<repo>/`.
5. Open the live URL on a phone to confirm every image loads. GitHub Pages is case sensitive
   and most laptops are not, so `Journey-Map.png` and `journey-map.png` are different files
   on the server.
6. Paste the live URL into the source link in the page header, and into the submission field.

## Note on the screenshots

The six phone screens in the artefact analysis section are captures of the live third-party
visitor system, reproduced as research evidence. They are not proposed designs. No interface
was designed in this project.

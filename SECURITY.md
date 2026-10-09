# Security

## Report a problem privately

If you find a security problem in this project, do not open a public issue.
A public issue tells everyone how to use the problem before it is fixed.

1. Open the Security tab of this repository.
2. Click "Report a vulnerability".
3. Write what you found, how to make it happen again, and what an attacker
   can do with it.

Only the owner of the repository can read the report. The owner answers on
the same report.

## What is checked

1. GitHub secret scanning reads every push. Push protection refuses a push
   that holds a known kind of key or token.
2. CodeQL reads the Python, the JavaScript and the workflow files on each
   push, and once a week.
3. Dependabot compares the pinned packages in
   `application/requirements.txt` and `application/package-lock.json` with
   the known vulnerabilities. For a vulnerable package, it opens a pull
   request with the fixed version.
4. Only the owner can push to `main`. Nobody can delete `main` or rewrite
   its history. A change from anyone else comes as a pull request, and it
   needs the three test checks to pass and the owner to merge it.

The app's own security design is in
[`application/docs/safety.md`](application/docs/safety.md).

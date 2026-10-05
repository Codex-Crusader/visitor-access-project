"""Every check in one command: the three test suites and both linters.

Run it from this folder with: .venv\\Scripts\\python.exe run_tests.py
It ends with a list of what passed and what failed, and exits with 1 if
anything failed or is missing. "The checks" in docs/maintenance.md says how
to install what it needs.
"""

import shutil
import subprocess
import sys


def tool(name: str) -> str | None:
    """The full path of a program on PATH, or None."""
    # The warning is about a path object on old Windows Pythons. name is text.
    # noinspection PyDeprecation
    return shutil.which(name)


CHECKS = [
    ("server tests", [sys.executable, "test_app.py"]),
    ("stress test", [sys.executable, "test_concurrency.py"]),
    ("page tests", [tool("node"), "test_form.js"] if tool("node") else None),
    ("ruff", [tool("ruff"), "check", "."] if tool("ruff") else None),
    ("eslint", [tool("npx"), "--no-install", "eslint", "static", "test_form.js"]
     if tool("npx") else None),
]
MISSING = {
    "page tests": "Node.js is not installed. Install it from https://nodejs.org,"
                  " then run npm install.",
    "ruff": "ruff is not installed. Run:"
            " .venv\\Scripts\\python.exe -m pip install ruff==0.16.2",
    "eslint": "npx is not installed. Install Node.js, then run npm install.",
}


def main():
    results = []
    for name, command in CHECKS:
        print(f"\n=== {name}", flush=True)
        if command is None:
            print(MISSING[name])
            results.append((name, "MISSING"))
            continue
        passed = subprocess.run(command).returncode == 0
        results.append((name, "passed" if passed else "FAILED"))
    print("\n=== summary")
    for name, result in results:
        print(f"{name:<13} {result}")
    return 0 if all(result == "passed" for _, result in results) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Every test and both linters. Run: .venv\\Scripts\\python.exe run_tests.py"""

import shutil
import subprocess
import sys
from pathlib import Path


def tool(name: str) -> str | None:
    """The full path of a program in this Python's own folder, then on PATH, or None."""
    here = str(Path(sys.executable).parent)
    # The warning is for a path argument on old Windows Pythons. name is text.
    # noinspection PyDeprecation
    return shutil.which(name, path=here) or shutil.which(name)


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
                  " then run npm ci.",
    "ruff": "ruff is not installed. Run:"
            " .venv\\Scripts\\python.exe -m pip install ruff==0.16.2",
    "eslint": "npx is not installed. Install Node.js, then run npm ci.",
}


def main():
    results = []
    for name, command in CHECKS:
        print(f"\n=== {name}", flush=True)
        if command is None:
            print(MISSING[name])
            results.append((name, "MISSING"))
            continue
        passed = subprocess.run(command, check=False).returncode == 0
        results.append((name, "passed" if passed else "FAILED"))
    print("\n=== summary")
    for name, result in results:
        print(f"{name:<13} {result}")
    return 0 if all(result == "passed" for _, result in results) else 1


if __name__ == "__main__":
    sys.exit(main())

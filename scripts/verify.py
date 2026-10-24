#!/usr/bin/env python3
"""Run local release gates without shell-specific commands."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(label: str, arguments: list[str]) -> bool:
    print(f"\n==> {label}: {sys.executable} {' '.join(arguments)}", flush=True)
    # Every argument vector comes from the fixed gate list below, not user/model input.
    result = subprocess.run([sys.executable, *arguments], cwd=ROOT, check=False)  # noqa: S603
    print(f"<== {label}: {'PASS' if result.returncode == 0 else 'FAIL'}", flush=True)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-lint", action="store_true")
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--pytest", action="store_true", help="Also run pytest after unittest")
    args = parser.parse_args()
    gates = [
        ("compile", ["-m", "compileall", "-q", "src", "tests", "scripts"]),
        ("tests", ["-m", "unittest", "discover", "-s", "tests", "-v"]),
    ]
    if args.pytest:
        gates.append(("pytest", ["-m", "pytest", "-q"]))
    if not args.skip_lint:
        if importlib.util.find_spec("ruff") is None:
            print("Ruff is required unless --skip-lint is explicit; install .[dev].")
            return 2
        gates.append(("ruff", ["-m", "ruff", "check", "src", "tests", "scripts"]))
    if not args.skip_audit:
        if importlib.util.find_spec("pip_audit") is None:
            print("pip-audit is required unless --skip-audit is explicit; install .[dev].")
            return 2
        gates.append(("dependency audit", ["-m", "pip_audit", "--progress-spinner", "off"]))
    passed = True
    for label, command in gates:
        passed = run(label, command) and passed
        if not passed:
            break
    print("\nRELEASE GATE:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

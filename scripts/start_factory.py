#!/usr/bin/env python3
"""One-click local bootstrap for the UAF dashboard. No API key is handled here."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PIP_VERSION = "26.2.2"
SETUPTOOLS_VERSION = "84.2.1"
BOOTSTRAP_FORMAT = 2
INSTALL_TIMEOUT_SECONDS = 900
BROWSER_INSTALL_TIMEOUT_SECONDS = 600
DOCTOR_TIMEOUT_SECONDS = 90


def venv_python(root: Path = ROOT) -> Path:
    venv = root / ".venv"
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def source_digest(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for name in ("pyproject.toml", "scripts/start_factory.py"):
        digest.update(name.encode("utf-8"))
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def dependency_commands(python: Path, *, with_computer_use: bool = False) -> list[list[str]]:
    executable = str(python)
    extra = "computer-use" if with_computer_use else "setup"
    return [
        [
            executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            f"pip=={PIP_VERSION}",
            f"setuptools=={SETUPTOOLS_VERSION}",
        ],
        [executable, "-m", "pip", "install", "--editable", f".[{extra}]"],
    ]


def dashboard_command(python: Path, *, port: int, no_open: bool) -> list[str]:
    command = [
        str(python),
        "-m",
        "uaf.cli",
        "dashboard",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    if no_open:
        command.append("--no-open")
    return command


def read_marker(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def write_marker(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def run_bounded(command: list[str], *, timeout: int, cwd: Path = ROOT) -> None:
    printable = " ".join(command)
    print(f"\n> {printable}", flush=True)
    subprocess.run(command, cwd=cwd, check=True, timeout=timeout)  # noqa: S603 - fixed argv, no shell


def dependencies_importable(python: Path, *, with_computer_use: bool = False) -> bool:
    modules = ("keyring", "playwright", "pyautogui") if with_computer_use else ("keyring",)
    result = subprocess.run(  # noqa: S603 - local venv interpreter, no shell
        [
            str(python),
            "-c",
            "import importlib.util as u; "
            f"raise SystemExit(not all(u.find_spec(n) for n in {modules!r}))",
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=30,
    )
    return result.returncode == 0


def prepare(
    *, skip_optional_browser: bool = False, with_computer_use: bool = False
) -> tuple[Path, dict[str, Any]]:
    if sys.version_info < (3, 11):  # noqa: UP036 - pre-install interpreter gate
        raise RuntimeError("Python 3.11 or newer is required. Run Start-UAF.cmd again.")
    ROOT.mkdir(exist_ok=True)  # Repository root already exists; never relocate it.
    python = venv_python()
    if not python.is_file():
        print("Creating a repository-local Python environment (.venv)…", flush=True)
        run_bounded([sys.executable, "-m", "venv", str(ROOT / ".venv")], timeout=300)

    marker_path = ROOT / ".venv" / "uaf-bootstrap.json"
    marker = read_marker(marker_path)
    digest = source_digest()
    if (
        marker.get("format") != BOOTSTRAP_FORMAT
        or marker.get("source_digest") != digest
        or marker.get("computer_use") != with_computer_use
        or not dependencies_importable(python, with_computer_use=with_computer_use)
    ):
        print(
            "Installing/updating only the local environment. First run needs internet; "
            "no system-wide package installation or administrator shell is used.",
            flush=True,
        )
        for command in dependency_commands(python, with_computer_use=with_computer_use):
            run_bounded(command, timeout=INSTALL_TIMEOUT_SECONDS)
        marker = {
            "format": BOOTSTRAP_FORMAT,
            "source_digest": digest,
            "computer_use": with_computer_use,
            "chromium": False,
        }
        write_marker(marker_path, marker)

    if with_computer_use and not skip_optional_browser and not marker.get("chromium"):
        print(
            "Preparing optional Chromium automation. The voice dashboard uses your normal "
            "browser and can still start if this optional download fails.",
            flush=True,
        )
        try:
            result = subprocess.run(  # noqa: S603 - optional local installer, no shell
                [str(python), "-m", "playwright", "install", "chromium"],
                cwd=ROOT,
                check=False,
                timeout=BROWSER_INSTALL_TIMEOUT_SECONDS,
            )
            chromium_ready = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as exc:
            # Optional browser automation must not prevent the core dashboard from opening.
            print(f"Optional Chromium setup stopped safely ({type(exc).__name__}).", flush=True)
            chromium_ready = False
        marker["chromium"] = chromium_ready
        write_marker(marker_path, marker)
        if not chromium_ready:
            print(
                "WARNING: Optional Chromium is not ready. The dashboard will still open; "
                "browser automation stays unavailable. Rerun the launcher when network access "
                "is available.",
                flush=True,
            )

    run_bounded([str(python), "-m", "uaf.cli", "init"], timeout=60)
    # Doctor is a real release gate for required local state. Optional feature warnings do
    # not block the lightweight dashboard; missing DB/config/workspace requirements do.
    run_bounded([str(python), "-m", "uaf.cli", "doctor", "--json"], timeout=DOCTOR_TIMEOUT_SECONDS)
    return python, marker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare and open the local UAF company dashboard")
    parser.add_argument("--port", type=int, default=0, help="Dashboard port; 0 selects a free port")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument(
        "--with-computer-use",
        action="store_true",
        help="Also install optional Playwright/PyAutoGUI and prepare Chromium",
    )
    parser.add_argument(
        "--skip-optional-browser",
        action="store_true",
        help="With computer-use, skip only the optional Chromium download",
    )
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65_535:
        parser.error("port must be between 0 and 65535")
    try:
        python, _ = prepare(
            skip_optional_browser=args.skip_optional_browser,
            with_computer_use=args.with_computer_use,
        )
        print(
            "\nLocal checks passed. Opening the private dashboard. "
            "Enter the Gemini API key only in that local page.",
            flush=True,
        )
        return subprocess.call(  # noqa: S603 - fixed local dashboard argv, no shell
            dashboard_command(python, port=args.port, no_open=args.no_open), cwd=ROOT
        )
    except subprocess.TimeoutExpired as exc:
        print(
            f"Setup exceeded its bounded timeout ({exc.timeout}s). No unbounded retry was made.",
            file=sys.stderr,
        )
        return 2
    except subprocess.CalledProcessError as exc:
        print(
            f"Setup stopped at a failed command (exit {exc.returncode}). Fix the displayed "
            "local/network issue and rerun Start-UAF.cmd; committed state is preserved.",
            file=sys.stderr,
        )
        return exc.returncode or 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Setup could not start: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

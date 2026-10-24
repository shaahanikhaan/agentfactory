from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "uaf_start_factory", ROOT / "scripts/start_factory.py"
)
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    def test_command_plan_is_local_bounded_and_contains_no_credentials(self):
        python = Path("venv/python")
        commands = bootstrap.dependency_commands(python)
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(isinstance(command, list) for command in commands))
        self.assertIn("pip==26.2.2", commands[0])
        self.assertIn("setuptools==84.2.1", commands[0])
        self.assertIn(".[setup]", commands[1])
        self.assertNotIn(".[computer-use]", commands[1])
        computer_use = bootstrap.dependency_commands(python, with_computer_use=True)
        self.assertIn(".[computer-use]", computer_use[1])
        dashboard = bootstrap.dashboard_command(python, port=8765, no_open=True)
        self.assertIn("127.0.0.1", dashboard)
        self.assertIn("--no-open", dashboard)
        self.assertNotIn("0.0.0.0", dashboard)  # noqa: S104 - assert wildcard bind is absent
        self.assertNotIn("api_key", json.dumps(commands + [dashboard]).lower())
        self.assertGreater(bootstrap.INSTALL_TIMEOUT_SECONDS, 0)
        self.assertLessEqual(bootstrap.INSTALL_TIMEOUT_SECONDS, 900)

    def test_marker_round_trip_and_corrupt_marker_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "marker.json"
            bootstrap.write_marker(marker, {"format": 1, "chromium": True})
            self.assertEqual(bootstrap.read_marker(marker)["chromium"], True)
            marker.write_text("not-json", encoding="utf-8")
            self.assertEqual(bootstrap.read_marker(marker), {})

    def test_doctor_failure_prevents_dashboard_launch(self):
        with (
            mock.patch.object(
                bootstrap,
                "prepare",
                side_effect=subprocess.CalledProcessError(2, ["uaf", "doctor"]),
            ),
            mock.patch.object(bootstrap.subprocess, "call") as launch,
        ):
            result = bootstrap.main(["--skip-optional-browser", "--no-open"])
        self.assertEqual(result, 2)
        launch.assert_not_called()

    def test_successful_prepare_launches_loopback_dashboard(self):
        python = Path("fake/.venv/python")
        with (
            mock.patch.object(bootstrap, "prepare", return_value=(python, {})) as prepare,
            mock.patch.object(bootstrap.subprocess, "call", return_value=0) as launch,
        ):
            result = bootstrap.main(["--skip-optional-browser", "--no-open"])
        self.assertEqual(result, 0)
        prepare.assert_called_once_with(skip_optional_browser=True, with_computer_use=False)
        command = launch.call_args.args[0]
        self.assertIn("127.0.0.1", command)
        self.assertIn("--no-open", command)
        self.assertEqual(command[command.index("--port") + 1], "0")

    def test_default_lightweight_prepare_never_invokes_chromium(self):
        with tempfile.TemporaryDirectory() as tmp:
            python = Path(tmp) / "python"
            python.touch()
            marker = {
                "format": bootstrap.BOOTSTRAP_FORMAT,
                "source_digest": "digest",
                "computer_use": False,
                "chromium": False,
            }
            with (
                mock.patch.object(bootstrap, "venv_python", return_value=python),
                mock.patch.object(bootstrap, "source_digest", return_value="digest"),
                mock.patch.object(bootstrap, "read_marker", return_value=marker),
                mock.patch.object(bootstrap, "dependencies_importable", return_value=True),
                mock.patch.object(bootstrap, "run_bounded"),
                mock.patch.object(bootstrap, "write_marker") as write_marker,
                mock.patch.object(bootstrap.subprocess, "run") as installer,
            ):
                _, returned = bootstrap.prepare()
            self.assertFalse(returned["computer_use"])
            installer.assert_not_called()
            write_marker.assert_not_called()

    def test_optional_browser_timeout_or_os_error_does_not_abort_setup(self):
        for failure in (
            subprocess.TimeoutExpired(["playwright"], 600),
            OSError("optional installer unavailable"),
        ):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                python = Path(tmp) / "python"
                python.touch()
                marker = {
                    "format": bootstrap.BOOTSTRAP_FORMAT,
                    "source_digest": "digest",
                    "computer_use": True,
                    "chromium": False,
                }
                with (
                    mock.patch.object(bootstrap, "venv_python", return_value=python),
                    mock.patch.object(bootstrap, "source_digest", return_value="digest"),
                    mock.patch.object(bootstrap, "read_marker", return_value=marker),
                    mock.patch.object(bootstrap, "dependencies_importable", return_value=True),
                    mock.patch.object(bootstrap, "run_bounded"),
                    mock.patch.object(bootstrap, "write_marker") as write_marker,
                    mock.patch.object(bootstrap.subprocess, "run", side_effect=failure),
                ):
                    _, returned = bootstrap.prepare(with_computer_use=True)
                self.assertFalse(returned["chromium"])
                self.assertTrue(write_marker.called)

    def test_cmd_entry_point_uses_project_local_bootstrap(self):
        command = (ROOT / "Start-UAF.cmd").read_text(encoding="utf-8")
        self.assertIn('cd /d "%~dp0"', command)
        self.assertIn("py -3.11", command)
        self.assertIn(r"scripts\start_factory.py", command)
        self.assertNotIn("GEMINI_API_KEY", command)
        self.assertNotIn("pip install", command.lower())
        self.assertNotIn("Set-ExecutionPolicy", command)


if __name__ == "__main__":
    unittest.main()

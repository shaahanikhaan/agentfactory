from __future__ import annotations

import os
import unittest

from tests.support import FactoryCase
from uaf.errors import ValidationError
from uaf.models import TaskContract
from uaf.repository import MAX_OUTPUT_CHARS, MAX_SOURCE_BYTES, PythonRepositoryMap
from uaf.util import canonical_json


class RepositoryMapTests(FactoryCase):
    def test_real_ast_map_does_not_execute_source(self):
        package = self.workspace / "pkg"
        package.mkdir()
        (package / "core.py").write_text(
            "import os\n"
            "from json import dumps\n"
            "raise RuntimeError('AST mapping must not execute this')\n"
            "class Worker:\n"
            "    def run(self):\n"
            "        return os.name\n"
            "async def fetch():\n"
            "    return dumps({})\n",
            encoding="utf-8",
        )
        (package / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        (package / ".env.py").write_text("SECRET = 'hidden'\n", encoding="utf-8")
        (package / "large.py").write_bytes(b"#" * (MAX_SOURCE_BYTES + 1))
        hidden = self.workspace / ".venv"
        hidden.mkdir()
        (hidden / "hidden.py").write_text("raise RuntimeError('hidden')\n", encoding="utf-8")

        result = PythonRepositoryMap(self.app.workspace).build("pkg", limit=10)
        self.assertFalse(result["code_executed"])
        self.assertTrue(result["truncated"])  # Large source is explicitly reported.
        self.assertEqual(result["skipped_large_files"], 1)
        modules = {module["path"]: module for module in result["modules"]}
        core = modules["pkg/core.py"]
        self.assertEqual(core["imports"], ["json", "os"])
        self.assertEqual(core["symbols"][0]["kind"], "class")
        self.assertEqual(core["symbols"][0]["methods"], ["run"])
        self.assertEqual(core["symbols"][1]["kind"], "async_function")
        self.assertEqual(modules["pkg/broken.py"]["error"], "syntax_error")
        self.assertNotIn("pkg/.env.py", str(result))
        self.assertNotIn("hidden.py", str(result))

    def test_governed_tool_task_returns_real_repository_evidence(self):
        (self.workspace / "real_module.py").write_text(
            "def actual_function():\n    return 42\n", encoding="utf-8"
        )
        task = self.tasks.add(
            TaskContract(
                goal="Map the actual Python repository",
                kind="tool",
                input_data={
                    "tool": "workspace.python_map",
                    "arguments": {"path": ".", "limit": 10},
                },
                allowed_tools=["workspace.python_map"],
            )
        )
        result = self.app.runner.run(task["task_id"])
        self.assertEqual(result["state"], "succeeded")
        self.assertFalse(result["result"]["ai_generated"])
        output = result["result"]["output"]
        self.assertEqual(output["modules"][0]["path"], "real_module.py")
        self.assertEqual(output["modules"][0]["symbols"][0]["name"], "actual_function")
        self.assertEqual(
            self.db.one(
                "SELECT COUNT(*) c FROM tool_invocations WHERE tool_name='workspace.python_map'"
            )["c"],
            1,
        )

    def test_traversal_and_symlink_escape_are_not_mapped(self):
        mapper = PythonRepositoryMap(self.app.workspace)
        with self.assertRaises(ValidationError):
            mapper.build("../")
        outside = self.root / "outside.py"
        outside.write_text("def outside():\n    pass\n", encoding="utf-8")
        link = self.workspace / "link.py"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            return
        result = mapper.build()
        self.assertNotIn("outside.py", str(result["modules"]))

    def test_map_output_is_bounded_and_honestly_truncated(self):
        for index in range(16):
            functions = "\n".join(
                f"def function_{index}_{item}():\n    return {item}\n" for item in range(70)
            )
            (self.workspace / f"module_{index}.py").write_text(functions, encoding="utf-8")
        result = PythonRepositoryMap(self.app.workspace).build(limit=100)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(canonical_json(result)), MAX_OUTPUT_CHARS)
        self.assertEqual(result["module_count"], len(result["modules"]))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

from uaf.app import Application
from uaf.config import AppPaths, ConfigManager

MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(MCP_AVAILABLE, "optional MCP SDK is not installed")
class MCPProtocolIntegrationTests(unittest.TestCase):
    def test_real_stdio_initialize_discover_call_and_shutdown(self):
        import anyio
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = AppPaths.discover(root / "home")
            manager = ConfigManager(paths)
            manager.initialize(root / "workspace")
            manager.set("mcp_enabled", True)
            with Application(paths) as app:
                app.memory.add("Approved MCP protocol memory", approved=True)

            environment = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(root),
                "PYTHONPATH": str(Path(__file__).parent.parent / "src"),
            }
            if os.name == "nt":
                for key in (
                    "SYSTEMROOT",
                    "WINDIR",
                    "USERPROFILE",
                    "APPDATA",
                    "LOCALAPPDATA",
                ):
                    if key in os.environ:
                        environment[key] = os.environ[key]
            else:
                environment["LC_ALL"] = "C.UTF-8"
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "uaf", "--home", str(paths.home), "mcp", "serve"],
                env=environment,
                cwd=Path(__file__).parent.parent,
            )

            async def exercise():
                with anyio.fail_after(30):
                    with (root / "server-stderr.log").open("w", encoding="utf-8") as errors:
                        async with (
                            stdio_client(parameters, errlog=errors) as (read, write),
                            ClientSession(read, write) as session,
                        ):
                            initialized = await session.initialize()
                            self.assertEqual(initialized.server_info.name, "ultimate-agent-factory")
                            tools = await session.list_tools()
                            self.assertEqual(
                                {tool.name for tool in tools.tools},
                                {"uaf_task_list", "uaf_task_add", "uaf_memory_search"},
                            )
                            added = await session.call_tool(
                                "uaf_task_add",
                                {"goal": "Real MCP stdio durable task", "kind": "smoke"},
                            )
                            self.assertFalse(added.is_error)
                            self.assertEqual(added.structured_content["state"], "queued")
                            memories = await session.call_tool(
                                "uaf_memory_search", {"query": "protocol", "limit": 5}
                            )
                            self.assertFalse(memories.is_error)
                            self.assertIn("Approved MCP", str(memories.model_dump()))

            anyio.run(exercise)
            with Application(paths) as app:
                goals = [row["goal"] for row in app.tasks.list()]
                self.assertIn("Real MCP stdio durable task", goals)


if __name__ == "__main__":
    unittest.main()

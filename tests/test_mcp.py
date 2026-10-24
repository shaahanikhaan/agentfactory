from __future__ import annotations

import unittest

from tests.support import FactoryCase
from uaf.mcp_server import register_narrow_tools


class Server:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorate(function):
            self.tools[function.__name__] = function
            return function

        return decorate


class MCPTests(FactoryCase):
    def test_only_narrow_tools_are_exposed(self):
        server = Server()
        register_narrow_tools(server, self.tasks, self.app.memory)
        self.assertEqual(set(server.tools), {"uaf_task_list", "uaf_task_add", "uaf_memory_search"})
        created = server.tools["uaf_task_add"]("offline smoke", "smoke")
        self.assertEqual(created["state"], "queued")
        self.assertEqual(server.tools["uaf_task_list"]()[0]["task_id"], created["task_id"])
        with self.assertRaises(ValueError):
            server.tools["uaf_task_add"]("dangerous", "tool")

    def test_memory_results_are_bounded(self):
        self.app.memory.add("MCP memory", approved=True)
        server = Server()
        register_narrow_tools(server, self.tasks, self.app.memory)
        rows = server.tools["uaf_memory_search"]("MCP", 1)
        self.assertEqual(len(rows), 1)
        with self.assertRaises(ValueError):
            server.tools["uaf_memory_search"]("MCP", 1000)


if __name__ == "__main__":
    unittest.main()

"""Optional official MCP SDK v2 server exposing only narrow UAF capabilities."""

from __future__ import annotations

from typing import Any

from uaf.errors import OptionalDependencyError
from uaf.memory import MemoryStore
from uaf.models import TaskContract
from uaf.tasks import TaskStore


def register_narrow_tools(server: Any, tasks: TaskStore, memory: MemoryStore) -> None:
    """Registration is separated for dependency-free contract tests."""

    @server.tool()
    def uaf_task_list(limit: int = 20) -> list[dict[str, Any]]:
        """List bounded local task metadata; no credentials or private memory are exposed."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return [
            {
                "task_id": row["task_id"],
                "goal": row["goal"],
                "state": row["state"],
                "kind": row["kind"],
                "updated_at": row["updated_at"],
            }
            for row in tasks.list(limit=limit)
        ]

    @server.tool()
    def uaf_task_add(goal: str, kind: str = "agent") -> dict[str, Any]:
        """Queue a local UAF task. This does not execute it or approve tools."""
        if kind not in {"agent", "smoke"}:
            raise ValueError("MCP task creation only permits agent or smoke kinds")
        task = tasks.add(TaskContract(goal=goal, kind=kind, requester="mcp-client"))
        return {"task_id": task["task_id"], "state": task["state"], "execution_required": True}

    @server.tool()
    def uaf_memory_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search approved non-deleted memories with bounded results."""
        if not 1 <= limit <= 25:
            raise ValueError("limit must be between 1 and 25")
        return [
            {
                "memory_id": row["memory_id"],
                "type": row["type"],
                "content": row["content"],
                "source": row["source"],
                "sensitivity": row["sensitivity"],
            }
            for row in memory.search(query, limit=limit, approved_only=True)
            if row["sensitivity"] != "private"
        ]


def serve(tasks: TaskStore, memory: MemoryStore) -> None:
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise OptionalDependencyError(
            "MCP support requires the optional stable SDK: python -m pip install -e '.[mcp]'"
        ) from exc
    server = MCPServer("ultimate-agent-factory")
    register_narrow_tools(server, tasks, memory)
    # stdio is the only enabled transport in this release. The launching local process
    # is the security boundary; no unauthenticated network listener is created.
    server.run(transport="stdio")

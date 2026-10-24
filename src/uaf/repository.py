"""Bounded, read-only Python repository mapping with the standard-library AST."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

from uaf.errors import ValidationError
from uaf.util import canonical_json, sha256_bytes
from uaf.workspace import Workspace

MAX_SOURCE_BYTES = 256_000
MAX_OUTPUT_CHARS = 24_000
_SKIPPED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def _imports(tree: ast.AST) -> list[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names[:24])
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            names.add(prefix + (node.module or ""))
    return sorted(names)[:24]


def _symbols(tree: ast.Module) -> list[dict[str, Any]]:
    symbols = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [
                child.name
                for child in node.body
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
            ][:16]
            symbols.append(
                {
                    "name": node.name,
                    "kind": "class",
                    "line": node.lineno,
                    "methods": methods,
                }
            )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            symbols.append(
                {
                    "name": node.name,
                    "kind": "async_function"
                    if isinstance(node, ast.AsyncFunctionDef)
                    else "function",
                    "line": node.lineno,
                }
            )
    return symbols[:48]


class PythonRepositoryMap:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def build(self, relative: str = ".", *, limit: int = 40) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValidationError("Repository map limit must be between 1 and 100")
        root = self.workspace.require_available()
        directory = root if relative == "." else self.workspace.resolve(relative, must_exist=True)
        directory = directory.resolve(strict=True)
        if not directory.is_relative_to(root) or not directory.is_dir():
            raise ValidationError("Repository map requires a confined workspace directory")

        modules = []
        errors = []
        skipped_large = 0
        truncated = False
        for current, dirnames, filenames in os.walk(directory, followlinks=False):
            kept = []
            for name in sorted(dirnames, key=str.casefold):
                child = Path(current, name)
                resolved = child.resolve(strict=False)
                if (
                    name.casefold() in _SKIPPED_DIRECTORIES
                    or child.is_symlink()
                    or not resolved.is_relative_to(root)
                ):
                    continue
                kept.append(name)
            dirnames[:] = kept
            for name in sorted(filenames, key=str.casefold):
                if not name.endswith(".py"):
                    continue
                if len(modules) >= limit:
                    truncated = True
                    break
                candidate = Path(current, name)
                if candidate.is_symlink():
                    continue
                try:
                    path = candidate.relative_to(root).as_posix()
                    resolved = self.workspace.resolve(path, must_exist=True)
                    if not resolved.is_file():
                        continue
                    if resolved.stat().st_size > MAX_SOURCE_BYTES:
                        skipped_large += 1
                        continue
                    data = resolved.read_bytes()
                    if len(data) > MAX_SOURCE_BYTES:
                        skipped_large += 1
                        continue
                except ValidationError:
                    continue
                except OSError:
                    if len(errors) < 20:
                        errors.append({"path": name, "error": "read_failed"})
                    continue
                try:
                    text = data.decode("utf-8")
                    tree = ast.parse(text, filename=path)
                except UnicodeDecodeError:
                    if len(errors) < 20:
                        errors.append({"path": path, "error": "not_utf8"})
                    continue
                except SyntaxError as exc:
                    modules.append(
                        {
                            "path": path,
                            "sha256": sha256_bytes(data),
                            "bytes": len(data),
                            "error": "syntax_error",
                            "line": exc.lineno,
                        }
                    )
                    continue
                modules.append(
                    {
                        "path": path,
                        "sha256": sha256_bytes(data),
                        "bytes": len(data),
                        "lines": len(text.splitlines()),
                        "imports": _imports(tree),
                        "symbols": _symbols(tree),
                    }
                )
            if truncated:
                break

        result = {
            "path": relative,
            "language": "python",
            "modules": modules,
            "module_count": len(modules),
            "truncated": truncated or skipped_large > 0 or bool(errors),
            "skipped_large_files": skipped_large,
            "errors": errors,
            "code_executed": False,
        }
        while len(canonical_json(result)) > MAX_OUTPUT_CHARS and result["modules"]:
            result["modules"].pop()
            result["truncated"] = True
        result["module_count"] = len(result["modules"])
        return result

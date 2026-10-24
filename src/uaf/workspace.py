"""Workspace confinement, removable-drive failure behavior, and reversible files."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

from uaf.errors import UnavailableError, ValidationError
from uaf.util import (
    atomic_write_bytes,
    atomic_write_text,
    canonical_json,
    file_digest,
    new_id,
    sha256_bytes,
)

_SENSITIVE_NAMES = {".env", "id_rsa", "id_ed25519", "credentials", "credentials.json"}
_SENSITIVE_SUFFIXES = {".pem", ".p12", ".pfx", ".key"}


class Workspace:
    def __init__(
        self, root: str | Path, backup_dir: str | Path, *, max_bytes: int = 1_000_000
    ) -> None:
        self.root_input = Path(root).expanduser().absolute()
        self.backup_dir = Path(backup_dir)
        self.max_bytes = max_bytes

    def available(self) -> bool:
        return self.root_input.is_dir()

    def require_available(self) -> Path:
        if not self.root_input.exists():
            raise UnavailableError(
                f"Workspace is unavailable (drive may be disconnected): {self.root_input}"
            )
        if not self.root_input.is_dir():
            raise ValidationError("Configured workspace is not a directory")
        return self.root_input.resolve(strict=True)

    def resolve(
        self, relative: str, *, must_exist: bool = False, allow_sensitive: bool = False
    ) -> Path:
        root = self.require_available()
        if not isinstance(relative, str) or not relative or "\x00" in relative:
            raise ValidationError("A non-empty workspace-relative path is required")
        windows = PureWindowsPath(relative)
        candidate_input = Path(relative)
        if candidate_input.is_absolute() or windows.is_absolute() or windows.drive:
            raise ValidationError("Absolute paths are not allowed in workspace tools")
        parts = [part for part in candidate_input.parts if part not in {"", "."}]
        if not parts or ".." in parts:
            raise ValidationError("Path traversal is not allowed")
        if not allow_sensitive:
            for part in parts:
                lowered = part.lower()
                if (
                    lowered == ".git"
                    or lowered in _SENSITIVE_NAMES
                    or lowered.startswith(".env.")
                    or Path(lowered).suffix in _SENSITIVE_SUFFIXES
                ):
                    raise ValidationError(
                        "Sensitive/version-control paths are not exposed by this tool"
                    )
        candidate = root.joinpath(*parts).resolve(strict=False)
        if not candidate.is_relative_to(root):
            raise ValidationError("Resolved path escapes the workspace (symlink/reparse point)")
        if must_exist and not candidate.exists():
            raise ValidationError(f"Workspace path does not exist: {relative}")
        return candidate

    def read_text(self, relative: str, *, max_bytes: int | None = None) -> dict:
        path = self.resolve(relative, must_exist=True)
        if not path.is_file():
            raise ValidationError("Only regular workspace files can be read")
        limit = min(max_bytes or self.max_bytes, self.max_bytes)
        size = path.stat().st_size
        if size > limit:
            raise ValidationError(f"File is {size} bytes; read limit is {limit}")
        data = path.read_bytes()
        if b"\x00" in data:
            raise ValidationError("Binary files require a dedicated optional adapter")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("File is not valid UTF-8 text") from exc
        return {"path": relative, "content": text, "bytes": len(data), "sha256": sha256_bytes(data)}

    def list(self, relative: str = ".", *, limit: int = 200) -> dict:
        if not 1 <= limit <= 1_000:
            raise ValidationError("List limit must be between 1 and 1000")
        directory = self.root_input if relative == "." else self.resolve(relative, must_exist=True)
        root = self.require_available()
        directory = directory.resolve()
        if not directory.is_relative_to(root) or not directory.is_dir():
            raise ValidationError("Only workspace directories can be listed")
        entries = []
        for child in sorted(directory.iterdir(), key=lambda item: item.name.lower()):
            lowered = child.name.lower()
            if (
                lowered == ".git"
                or lowered in _SENSITIVE_NAMES
                or lowered.startswith(".env.")
                or child.suffix.lower() in _SENSITIVE_SUFFIXES
            ):
                continue
            resolved = child.resolve(strict=False)
            if not resolved.is_relative_to(root):
                continue
            entries.append(
                {
                    "name": child.name,
                    "type": "directory" if child.is_dir() else "file",
                    "bytes": child.stat().st_size if child.is_file() else None,
                }
            )
            if len(entries) > limit:
                break
        return {
            "path": relative,
            "entries": entries[:limit],
            "truncated": len(entries) > limit,
        }

    def write_text(self, relative: str, content: str) -> dict:
        data = content.encode("utf-8")
        if len(data) > self.max_bytes:
            raise ValidationError(f"Write exceeds the {self.max_bytes}-byte tool limit")
        path = self.resolve(relative)
        backup = None
        if path.exists():
            if not path.is_file():
                raise ValidationError("Write target is not a regular file")
            backup = self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after parent creation to catch a replaced symlinked parent.
        path = self.resolve(relative)
        atomic_write_bytes(path, data)
        return {
            "path": relative,
            "bytes": len(data),
            "sha256": sha256_bytes(data),
            "backup_artifact": backup,
            "postcondition": path.is_file() and file_digest(path) == sha256_bytes(data),
        }

    def delete_file(self, relative: str) -> dict:
        path = self.resolve(relative)
        if not path.exists():
            return {"path": relative, "deleted": False, "already_absent": True}
        if not path.is_file():
            raise ValidationError("Delete tool only accepts a regular file, never a directory")
        backup = self._backup(path)
        path.unlink()
        return {
            "path": relative,
            "deleted": not path.exists(),
            "backup_artifact": backup,
            "postcondition": not path.exists(),
        }

    def _backup(self, path: Path) -> str:
        data = path.read_bytes()
        if len(data) > self.max_bytes:
            raise ValidationError(
                "Existing file is too large for the reversible-write backup budget"
            )
        backup_id = new_id("file")
        destination = self.backup_dir / f"{backup_id}.bin"
        atomic_write_bytes(destination, data, private=True)
        metadata = destination.with_suffix(".json")
        atomic_write_text(
            metadata,
            canonical_json({"original_name": path.name, "sha256": file_digest(destination)}) + "\n",
            private=True,
        )
        return backup_id

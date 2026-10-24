"""Progressively disclosed, checksummed skill instructions; skills grant no authority."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uaf.db import Database
from uaf.errors import IntegrityError, ValidationError
from uaf.util import canonical_json, file_digest, json_data, utc_now


class SkillLibrary:
    def __init__(self, db: Database) -> None:
        self.db = db

    def register_builtin(self) -> list[str]:
        root = Path(__file__).parent / "data" / "skills"
        return self.register_tree(root, builtin=True)

    def register_tree(self, root: Path, *, builtin: bool = False) -> list[str]:
        root = Path(root).resolve()
        registered = []
        for manifest_path in sorted(root.glob("*/skill.json")):
            registered.append(self.register(manifest_path, builtin=builtin))
        return registered

    def register(self, manifest_path: Path, *, builtin: bool = False) -> str:
        manifest_path = Path(manifest_path).resolve()
        if manifest_path.stat().st_size > 64_000:
            raise ValidationError("Skill manifest exceeds 64 KB")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationError(f"Invalid skill manifest: {exc}") from exc
        required = {
            "skill_id",
            "version",
            "name",
            "description",
            "triggers",
            "allowed_tools",
            "required_dependencies",
            "source",
            "license",
            "body",
            "sha256",
        }
        missing = required - set(manifest)
        if missing:
            raise ValidationError(f"Skill manifest missing: {sorted(missing)}")
        skill_id = manifest["skill_id"]
        if (
            not isinstance(skill_id, str)
            or not skill_id.replace("-", "").replace("_", "").isalnum()
        ):
            raise ValidationError("Invalid skill identifier")
        body = (manifest_path.parent / manifest["body"]).resolve()
        if not body.is_relative_to(manifest_path.parent) or not body.is_file():
            raise ValidationError("Skill body escapes its manifest directory")
        if body.stat().st_size > 128_000:
            raise ValidationError("Skill body exceeds 128 KB")
        actual = file_digest(body)
        if actual != manifest["sha256"]:
            raise IntegrityError(f"Skill {skill_id} body checksum mismatch")
        metadata = {
            key: manifest[key]
            for key in (
                "name",
                "description",
                "triggers",
                "allowed_tools",
                "required_dependencies",
                "source",
                "license",
                "resources",
            )
            if key in manifest
        }
        self.db.execute(
            "INSERT INTO skill_registry(skill_id,version,metadata_json,body_path,checksum,enabled,updated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(skill_id) DO UPDATE SET version=excluded.version,"
            "metadata_json=excluded.metadata_json,body_path=excluded.body_path,checksum=excluded.checksum,"
            "enabled=excluded.enabled,updated_at=excluded.updated_at",
            (
                skill_id,
                str(manifest["version"]),
                canonical_json(metadata),
                str(body),
                actual,
                int(builtin),
                utc_now(),
            ),
        )
        return skill_id

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT skill_id,version,metadata_json,checksum,enabled FROM skill_registry ORDER BY skill_id"
        )
        for row in rows:
            metadata = json_data(row.pop("metadata_json"), {})
            row.update(metadata)
            row["body_loaded"] = False
        return rows

    def load(self, skill_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM skill_registry WHERE skill_id=?", (skill_id,))
        if not row or not row["enabled"]:
            raise ValidationError(f"Unknown or disabled skill: {skill_id}")
        body = Path(row["body_path"])
        if not body.is_file() or file_digest(body) != row["checksum"]:
            raise IntegrityError("Skill body is missing or tampered; re-register explicitly")
        metadata = json_data(row["metadata_json"], {})
        return {
            "skill_id": skill_id,
            "version": row["version"],
            **metadata,
            "body": body.read_text(encoding="utf-8"),
            "authority": "Procedure only; allowed_tools remain subject to task/runtime policy",
        }

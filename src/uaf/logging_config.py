"""Redacted local logs; telemetry is never configured here."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from uaf.util import redact_text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        original = record.getMessage()
        record.msg = redact_text(original)
        record.args = ()
        return super().format(record)


def configure_logging(log_dir: Path, *, verbose: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("uaf")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.propagate = False
    if root.handlers:
        return
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "uaf.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)

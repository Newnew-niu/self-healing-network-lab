"""Append-only, tamper-evident audit log (JSON Lines).

Every record stores the SHA-256 of the previous record. If anyone edits or
deletes a line in the middle, `verify()` finds the broken link. The file is
only ever opened in append mode.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def _digest(prev_hash: str, body: dict[str, Any]) -> str:
    payload = prev_hash + json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = json.loads(line)["hash"]
        return last

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        body = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "event": event,
            **fields,
        }
        prev = self._last_hash()
        record = {**body, "prev_hash": prev, "hash": _digest(prev, body)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:  # append only, never "w"
            f.write(json.dumps(record, sort_keys=True) + "\n")
        return record

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def verify(self) -> tuple[bool, str]:
        prev = GENESIS
        for n, rec in enumerate(self.records(), start=1):
            body = {k: v for k, v in rec.items() if k not in ("prev_hash", "hash")}
            if rec["prev_hash"] != prev:
                return False, f"line {n}: prev_hash does not match line {n - 1}"
            if rec["hash"] != _digest(prev, body):
                return False, f"line {n}: content was modified"
            prev = rec["hash"]
        return True, "chain intact"

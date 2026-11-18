"""How netpulse talks to devices.

DockerRunner runs commands in the real lab with `docker exec`.
FixtureRunner answers the same calls from saved files, so unit tests and CI
run without a lab.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Protocol


class RunnerError(RuntimeError):
    pass


class Runner(Protocol):
    def vtysh(self, device: str, command: str) -> str: ...

    def shell(self, device: str, command: str) -> str: ...


def fixture_name(command: str) -> str:
    """'show bgp summary json' -> 'show_bgp_summary_json.txt'."""
    return re.sub(r"[^A-Za-z0-9]+", "_", command).strip("_") + ".txt"


class DockerRunner:
    def __init__(self, lab_name: str, timeout: float = 15.0) -> None:
        self.lab_name = lab_name
        self.timeout = timeout

    def _exec(self, device: str, argv: list[str]) -> str:
        container = f"clab-{self.lab_name}-{device}"
        try:
            proc = subprocess.run(
                ["docker", "exec", container, *argv],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"{device}: timeout running {argv}") from exc
        if proc.returncode != 0:
            raise RunnerError(f"{device}: {argv} failed: {proc.stderr.strip() or proc.stdout}")
        return proc.stdout

    def vtysh(self, device: str, command: str) -> str:
        return self._exec(device, ["vtysh", "-c", command])

    def vtysh_config(self, device: str, lines: list[str]) -> str:
        """Enter config mode and apply lines, e.g. ['interface eth1', 'no shutdown']."""
        argv = ["vtysh", "-c", "configure terminal"]
        for line in lines:
            argv += ["-c", line]
        return self._exec(device, argv)

    def shell(self, device: str, command: str) -> str:
        return self._exec(device, ["sh", "-c", command])


class FixtureRunner:
    """Reads tests/fixtures/<scenario>/<device>/<command>.txt."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _read(self, device: str, command: str) -> str:
        path = self.root / device / fixture_name(command)
        if not path.exists():
            raise RunnerError(f"no fixture {path}")
        return path.read_text(encoding="utf-8")

    def vtysh(self, device: str, command: str) -> str:
        return self._read(device, command)

    def shell(self, device: str, command: str) -> str:
        return self._read(device, command)

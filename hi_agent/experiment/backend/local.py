"""LocalBackend: subprocess-based experiment execution (G-9)."""
from __future__ import annotations

import logging
import shlex
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger(__name__)


@dataclass
class _ProcRecord:
    run_dir: Path
    proc: subprocess.Popen | None = None
    cancelled: bool = False


class LocalBackend:
    """Runs experiment commands as local subprocesses.

    Each submit() creates a dedicated run directory under work_dir/{external_id}/.
    stdout/stderr are written to stdout.log and stderr.log in that directory.
    """

    def __init__(self, work_dir: Path):
        self._work_dir = Path(work_dir)
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, _ProcRecord] = {}

    def submit(self, op_spec: dict) -> str:
        ext_id = str(uuid.uuid4())
        run_dir = self._work_dir / ext_id
        run_dir.mkdir(parents=True, exist_ok=True)

        command = op_spec.get("command", "")
        if isinstance(command, str):
            argv = shlex.split(command, posix=(sys.platform != "win32"))
        elif isinstance(command, list):
            argv = [str(a) for a in command]
        else:
            argv = []

        if not argv:
            _logger.warning("LocalBackend.submit: empty command for ext_id=%s", ext_id)
            record = _ProcRecord(run_dir=run_dir, proc=None)
            self._records[ext_id] = record
            return ext_id

        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"

        try:
            proc = subprocess.Popen(
                argv,
                stdout=stdout_path.open("w"),
                stderr=stderr_path.open("w"),
                cwd=run_dir,
            )
            self._records[ext_id] = _ProcRecord(run_dir=run_dir, proc=proc)
            _logger.info("LocalBackend submitted ext_id=%s pid=%s cmd=%s", ext_id, proc.pid, argv[:1])
        except (FileNotFoundError, PermissionError) as exc:
            _logger.warning("LocalBackend.submit failed: %s", exc)
            self._records[ext_id] = _ProcRecord(run_dir=run_dir, proc=None, cancelled=True)

        return ext_id

    def status(self, external_id: str) -> str:
        record = self._records.get(external_id)
        if record is None:
            return "unknown"
        if record.cancelled:
            return "cancelled"
        proc = record.proc
        if proc is None:
            return "failed"  # empty command or failed to start
        rc = proc.poll()
        if rc is None:
            return "running"
        return "succeeded" if rc == 0 else "failed"

    def fetch_artifacts(self, external_id: str) -> list[str]:
        record = self._records.get(external_id)
        if record is None or not record.run_dir.exists():
            return []
        return [str(p) for p in record.run_dir.iterdir() if p.is_file()]

    def cancel(self, external_id: str) -> None:
        record = self._records.get(external_id)
        if record is None:
            return
        record.cancelled = True
        if record.proc is not None and record.proc.poll() is None:
            record.proc.terminate()
            _logger.info("LocalBackend cancelled ext_id=%s", external_id)

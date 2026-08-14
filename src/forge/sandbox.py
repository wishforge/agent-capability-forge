"""M13 - deterministic Docker sandbox launcher.

Shared by oracle, B3 validation/evaluation/invoke. Fail-closed: no daemon
-> exception, never falls back to a bare process. Network is always off.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path


def launch(image: str, mounts: list[tuple[Path | str, str, bool]], cmd: list[str],
           limits: dict | None = None) -> dict:
    """Run `cmd` in a fresh container.

    mounts: (host_path, container_path, read_only)
    limits: {timeout_seconds, output_bytes}
    """
    limits = limits or {}
    timeout_s = limits.get("timeout_seconds", 120)
    output_bytes = limits.get("output_bytes", 1_048_576)
    sandbox_id = "cbx-" + uuid.uuid4().hex[:12]
    args = ["docker", "run", "--rm", "--network", "none", "--name", sandbox_id]
    for host, cont, ro in mounts:
        args += ["-v", f"{Path(host)}:{cont}:{'ro' if ro else 'rw'}"]
    args += [image, *cmd]
    started = time.monotonic()
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout_s)
        timed_out = False
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", sandbox_id], capture_output=True)
        proc = None
        timed_out = True
    elapsed = time.monotonic() - started
    if timed_out:
        return {"sandbox_id": sandbox_id, "exit_code": None, "stdout": "",
                "stderr": f"timed out after {timeout_s}s", "elapsed_s": round(elapsed, 3),
                "timed_out": True}
    out = (proc.stdout or b"").decode("utf-8", "replace")[:output_bytes]
    err = (proc.stderr or b"").decode("utf-8", "replace")[:output_bytes]
    return {"sandbox_id": sandbox_id, "exit_code": proc.returncode, "stdout": out,
            "stderr": err, "elapsed_s": round(elapsed, 3), "timed_out": False}

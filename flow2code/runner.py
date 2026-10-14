"""Running the generated program.

The generated file is executed in a separate process with a timeout, and the user's input is
fed on stdin.  No eval(), no exec(): a flowchart drawn by a student should never be able to
make the host process do something it was not asked to do.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Result:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out

    def describe(self) -> str:
        if self.timed_out:
            return "the program ran out of time (a loop that never ends?)"
        out = self.stdout if self.stdout.strip() else "(no output)"
        if self.code != 0:
            tail = [l for l in self.stderr.strip().splitlines() if l.strip()]
            return f"exit {self.code}: {tail[-1] if tail else 'error'}\n{out}"
        return out


def run(source: str, stdin: str = "", timeout: float = 5.0,
        keep: Optional[Path] = None) -> Result:
    """Write ``source`` to a .py file and run it with this same interpreter."""
    if keep is not None:
        p = Path(keep)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(source, encoding="utf-8")
        target = p
        tmp = None
    else:
        d = tempfile.mkdtemp(prefix="flow2code_")
        target = Path(d) / "generated.py"
        target.write_text(source, encoding="utf-8")
        tmp = d
    try:
        proc = subprocess.run([sys.executable, str(target)], input=stdin, capture_output=True,
                              text=True, timeout=timeout)
        return Result(proc.returncode, proc.stdout, proc.stderr)
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return Result(-1, out, "timed out", timed_out=True)
    finally:
        if tmp:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

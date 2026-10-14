"""Reading and writing the one file format this tool has: a chart as JSON.

A chart is data, not code, so it can be saved, diffed in git, and used as a test fixture.
That is also why the generator can be tested without a screen or a camera.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from .graph import Flow2CodeError
from .models import Flowchart

PathLike = Union[str, Path]


def load_flowchart(path: PathLike) -> Flowchart:
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Flow2CodeError(f"no chart file at {p}") from None
    except json.JSONDecodeError as exc:
        raise Flow2CodeError(f"{p} is not valid JSON ({exc.msg} at line {exc.lineno})") from None
    if not isinstance(raw, dict) or "nodes" not in raw:
        raise Flow2CodeError(f"{p} does not look like a chart: it needs 'nodes' (and 'edges')")
    return Flowchart.from_dict(raw)


def save_flowchart(fc: Flowchart, path: PathLike) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(fc.to_dict(), indent=2) + "\n", encoding="utf-8")
    return p


def from_json_text(text: str) -> Flowchart:
    return Flowchart.from_dict(json.loads(text))

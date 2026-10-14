import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))          # run against the source tree, no install step needed

import pytest


@pytest.fixture
def chart():
    """Load samples/<name>.flow.json"""
    from flow2code.loader import load_flowchart

    def _load(name):
        return load_flowchart(ROOT / "samples" / f"{name}.flow.json")
    return _load

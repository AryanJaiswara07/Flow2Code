"""Straightening a chart that came off paper or out of a drag-and-drop.

Nobody lays blocks on a grid while drawing by hand, and a tidy chart is easier for a reader
— human or generator — to follow.  The rule is the one textbooks use: one row per level of
distance from Start, the row centred on the spine, everything read top to bottom.  Depth
comes from the same reachability walk the validator already does, so the layout can never
disagree with what the code generator will do with the chart.
"""
from __future__ import annotations

import networkx as nx

from .graph import build
from .models import default_size

GAP_Y = 56            # ink-free space between two rows
GAP_X = 70            # ink-free space between two blocks in one row
LEFT, TOP = 110.0, 70.0
MIDDLE = 380.0        # the spine everything is centred on


def size_of(node) -> tuple:
    """The box a node occupies: a hand-picked w/h wins, otherwise the size for its type."""
    return (node.w or default_size(node.type)[0], node.h or default_size(node.type)[1])


def row_height(nodes) -> float:
    return max((size_of(n)[1] for n in nodes), default=60.0)


def auto_layout(fc, top: float = TOP, middle: float = MIDDLE) -> None:
    """Move ``fc``'s nodes into rows by depth from Start.  In place; returns nothing."""
    if not fc.nodes:
        return
    g = build(fc)
    starts = [n for n in fc.nodes if n.type == "start"]
    if not starts:
        return
    try:
        depth = nx.single_source_shortest_path_length(g, starts[0].id)
    except nx.NetworkXError:
        return

    rows: dict = {}
    for n in fc.nodes:
        rows.setdefault(depth.get(n.id, 0), []).append(n)
    for row in rows.values():
        row.sort(key=lambda n: (n.x, n.y))         # keep the drawing's left-to-right intent

    y = top
    for d in sorted(rows):
        row = rows[d]
        height = row_height(row)
        total = sum(size_of(n)[0] for n in row) + GAP_X * (len(row) - 1)
        x = middle - total / 2
        for n in row:
            w, h = size_of(n)
            n.x = x + w / 2
            n.y = y + height / 2
            x += w + GAP_X
        y += height + GAP_Y
    _settle(fc)


def _settle(fc) -> None:
    """Nothing off-canvas: the leftmost edge lands at x=110+, the topmost at y=70."""
    left = min(n.x - size_of(n)[0] / 2 for n in fc.nodes)
    top = min(n.y - size_of(n)[1] / 2 for n in fc.nodes)
    dx = max(0.0, LEFT - left)
    dy = max(0.0, TOP - top)
    if dx or dy:
        for n in fc.nodes:
            n.x, n.y = n.x + dx, n.y + dy

"""The part of the editor that does not need a screen.

Kept separate from the Tkinter window for one reason: this is where the rules live (what may be
connected to what, hit-testing, undo), and rules you can test are rules you can trust.  The
window is then only drawing and mouse events.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..codegen import generate
from ..graph import Flow2CodeError, build, problems, validate
from ..models import Edge, Flowchart, NODE_TYPES, Node

BLOCK_W, BLOCK_H = 150, 60           # click target, not the drawn size (draw.py owns that)


class EditorState:
    """A chart plus the operations a person would expect of an editor."""

    def __init__(self, fc: Optional[Flowchart] = None):
        self.fc = fc or Flowchart(name="untitled", nodes=[], edges=[])
        self._undo: List[str] = []
        self.message = ""

    # ------------------------------------------------------------------ chart helpers
    @property
    def nodes(self) -> List[Node]:
        return self.fc.nodes

    @property
    def edges(self) -> List[Edge]:
        return self.fc.edges

    def snapshot(self) -> str:
        import json

        return json.dumps(self.fc.to_dict(), sort_keys=True)

    def push_undo(self) -> None:
        self._undo.append(self.snapshot())
        del self._undo[:-40]                          # a long session should not grow forever

    def undo(self) -> bool:
        import json

        if not self._undo:
            self.message = "nothing to undo"
            return False
        self.fc = Flowchart.from_dict(json.loads(self._undo.pop()))
        self.message = "undone"
        return True

    # ------------------------------------------------------------------ editing
    def add_block(self, type_: str, x: float, y: float, text: str = "") -> str:
        if type_ not in NODE_TYPES:
            raise Flow2CodeError(f"unknown block type {type_!r}; use one of {', '.join(NODE_TYPES)}")
        nid = self._next_id()
        default = {"start": "Start", "end": "End", "input": "Read n",
                   "output": 'Print "result"', "process": "total = 0",
                   "decision": "n > 0?"}[type_]
        self.push_undo()
        self.fc.nodes.append(Node(nid, type_, text or default, x, y))
        self.message = f"added {type_} block {nid}"
        return nid

    def move_block(self, nid: str, x: float, y: float) -> None:
        n = self.fc.by_id().get(nid)
        if n is None:
            return
        if (n.x, n.y) == (x, y):
            return
        self.push_undo()
        n.x, n.y = x, y

    def set_text(self, nid: str, text: str) -> None:
        n = self.fc.by_id().get(nid)
        if n is None or n.text == text:
            return
        self.push_undo()
        n.text = text
        self.message = f"{nid}: {text or '(empty)'}"

    def set_type(self, nid: str, type_: str) -> None:
        if type_ not in NODE_TYPES:
            raise Flow2CodeError(f"unknown block type {type_!r}")
        n = self.fc.by_id().get(nid)
        if n is None:
            return
        self.push_undo()
        n.type = type_
        self.message = f"{nid} is now a {type_} block"

    def delete_block(self, nid: str) -> None:
        self.push_undo()
        self.fc.nodes = [n for n in self.fc.nodes if n.id != nid]
        self.fc.edges = [e for e in self.fc.edges if nid not in (e.src, e.dst)]
        self.message = f"deleted {nid}"

    def connect(self, src: str, dst: str) -> Optional[Edge]:
        """Draw an arrow.  Refuses the two things that are never what the user meant."""
        if src == dst:
            raise Flow2CodeError("an arrow into its own block is not a loop, it is a mistake")
        nodes = self.fc.by_id()
        if src not in nodes or dst not in nodes:
            raise Flow2CodeError("both ends of an arrow have to be blocks in this chart")
        if any(e.src == src and e.dst == dst for e in self.fc.edges):
            self.message = "that arrow is already there"
            return None
        if nodes[src].type == "decision" and len(self.fc.out(src)) >= 2:
            raise Flow2CodeError(f"a decision has exactly two arrows, and {src!r} "
                                 f"({nodes[src].text!r}) already has both")
        self.push_undo()
        e = Edge(src, dst, self._free_label(src))
        self.fc.edges.append(e)
        self.message = (f"{src} -> {dst} ({e.label})" if e.label else f"{src} -> {dst}")
        return e

    def _free_label(self, src: str) -> str:
        if self.fc.by_id()[src].type != "decision":
            return ""
        used = {e.label for e in self.fc.out(src)}
        return "yes" if "yes" not in used else ("no" if "no" not in used else "")

    def toggle_label(self, src: str, dst: str) -> None:
        """For a decision branch: yes <-> no <-> (unset)."""
        for e in self.fc.edges:
            if e.src == src and e.dst == dst:
                self.push_undo()
                e.label = {"": "yes", "yes": "no", "no": ""}[e.label]
                self.message = f"{src}->{dst} is now {e.label or 'unlabelled'}"
                return
        self.message = "no such arrow"

    def delete_edge(self, src: str, dst: str) -> None:
        before = len(self.fc.edges)
        self.push_undo()
        self.fc.edges = [e for e in self.fc.edges if not (e.src == src and e.dst == dst)]
        self.message = "arrow deleted" if len(self.fc.edges) < before else "no such arrow"

    # ------------------------------------------------------------------ geometry
    def hit_test(self, x: float, y: float) -> Optional[str]:
        """The topmost block under a point, or None.  Diamond points hit the diamond, not its box."""
        for n in reversed(self.fc.nodes):
            if abs(x - n.x) <= BLOCK_W / 2 and abs(y - n.y) <= BLOCK_H / 2:
                if n.type == "decision":
                    dx, dy = abs(x - n.x) / (BLOCK_W / 2), abs(y - n.y) / (BLOCK_H / 2)
                    if dx + dy > 1.15:
                        continue
                return n.id
        return None

    def edge_hit(self, x: float, y: float, tol: float = 9.0) -> Optional[Tuple[str, str]]:
        """The arrow nearest a point, if any: so a click on a line can delete or relabel it."""
        best, bestd = None, tol
        for e in self.fc.edges:
            a, b = self._anchor_of(e.src, x, y), self._anchor_of(e.dst, x, y)
            if a is None or b is None:
                continue
            d = _dist_to_segment((x, y), a, b)
            if d < bestd:
                best, bestd = (e.src, e.dst), d
        return best

    def _anchor_of(self, nid: str, x: float, y: float) -> Optional[Tuple[float, float]]:
        n = self.fc.by_id().get(nid)
        if n is None:
            return None
        dx, dy = x - n.x, y - n.y
        if abs(dx) > abs(dy):
            return (n.x + (BLOCK_W / 2) * (1 if dx > 0 else -1), n.y)
        return (n.x, n.y + (BLOCK_H / 2) * (1 if dy > 0 else -1))

    # ------------------------------------------------------------------ the two answers
    def check(self) -> List[str]:
        """Every problem, in the order the validator found them."""
        return problems(self.fc, build(self.fc))

    def code(self, annotate: bool = False) -> str:
        return generate(self.fc, validate(self.fc, build(self.fc)), annotate=annotate,
                        header=False)

    def as_dict(self) -> dict:
        return self.fc.to_dict()

    # ------------------------------------------------------------------ naming
    def _next_id(self) -> str:
        used = {n.id for n in self.fc.nodes}
        i = 1
        while f"n{i}" in used:
            i += 1
        return f"n{i}"


def _dist_to_segment(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L))
    return ((px - (ax + t * vx)) ** 2 + (py - (ay + t * vy)) ** 2) ** 0.5

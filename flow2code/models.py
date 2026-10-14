"""The data model: a flowchart is a directed graph with typed nodes, plus free notes.

A node type carries four things, and they are all declared in :data:`NODE_KINDS` so there is
exactly one place where the vocabulary of this tool lives:

  * **shape**  how it is drawn (and, in photo mode, how it is recognised);
  * **out**    how many arrows may leave it - which is what makes the validator's rules data
               rather than a pile of ``if`` statements;
  * **code**   what it means in Python: a statement, a read, a print, a test, a pass-through
               connector, or nothing at all for the two terminals.

    start / end        oval          the entry and the exit, no code
    input              parallelogram a read    ->  n = int(input("Enter n: "))
    output             parallelogram a print   ->  print("Even")
    process            rectangle     one statement, copied after a parse check
    decision           diamond       a test    ->  if / else, or while if an arrow comes back
    document           wavy bottom   a statement (a report or a printed artefact)
    database           cylinder      a statement (a read or write of stored data)
    manual             trapezoid     a statement someone keys in
    preparation        hexagon       a statement that primes a variable (loop counters)
    delay              dome          a statement, drawn as a wait
    connector          circle        joins two halves of a long arrow: no code
    offpage            pentagon      leaves this page and comes back: no code

Notes are not nodes: they are annotations on the drawing, they never join the graph, and the
generator ignores them.  That is deliberate - a comment that a reader can see must not become a
block the validator insists on reaching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

#: what each type means.  ``code`` is the translation strategy in statement.py;
#: ``out`` is the required out-degree; ``shape`` is the drawing in draw.py and the target
#: of the shape classifier in vision.py.
NODE_KINDS: Dict[str, dict] = {
    "start":       dict(shape="terminal",    code="none",        out=1, group="terminals",
                       label="Start / terminator", hint="Start"),
    "end":         dict(shape="terminal",    code="none",        out=0, group="terminals",
                       label="End / terminator", hint="End"),
    "input":       dict(shape="io",          code="read",        out=1, group="data",
                       label="Data in", hint="Read n"),
    "output":      dict(shape="io",          code="write",       out=1, group="data",
                       label="Data out", hint='Print "result"'),
    "process":     dict(shape="rect",        code="statement",   out=1, group="process",
                       label="Process", hint="total = 0"),
    "decision":    dict(shape="diamond",     code="condition",   out=2, group="process",
                       label="Decision", hint="n > 0?"),
    "document":    dict(shape="document",    code="statement",   out=1, group="documents",
                       label="Document", hint="report = make_note()"),
    "database":    dict(shape="database",    code="statement",   out=1, group="documents",
                       label="Database", hint="row = store.read(n)"),
    "manual":      dict(shape="manual",      code="statement",   out=1, group="documents",
                       label="Manual input", hint="signed = key_in()"),
    "preparation": dict(shape="hexagon",     code="statement",   out=1, group="process",
                       label="Preparation", hint="i = 0"),
    "delay":       dict(shape="delay",       code="statement",   out=1, group="process",
                       label="Delay", hint="wait = sleep_for"),
    "connector":   dict(shape="circle",      code="pass",        out=1, group="links",
                       label="Connector", hint="A"),
    "offpage":     dict(shape="pentagon",    code="pass",        out=1, group="links",
                       label="Off-page", hint="B"),
}

NODE_TYPES = tuple(NODE_KINDS)

#: out-degree required by each type, read straight from the table above
OUT_DEGREE = {k: v["out"] for k, v in NODE_KINDS.items()}

#: which types may carry a Yes / No label on their outgoing edge
LABELLED = {k for k, v in NODE_KINDS.items() if v["code"] == "condition"}

#: types whose text becomes Python statements, and types that only route
STATEMENT_CODES = {"read", "write", "statement", "condition"}


def shape_of(type_: str) -> str:
    return NODE_KINDS[type_]["shape"]


def code_of(type_: str) -> str:
    return NODE_KINDS[type_]["code"]


def default_size(type_: str) -> Tuple[float, float]:
    """The box a block of ``type_`` gets when the chart itself does not say otherwise."""
    return DEFAULT_SIZE[shape_of(type_)]


#: default drawing size per shape; a node may override it with w / h
DEFAULT_SIZE = {
    "terminal": (104, 48), "io": (160, 60), "rect": (160, 60), "diamond": (176, 100),
    "document": (160, 66), "database": (150, 74), "manual": (160, 60),
    "hexagon": (170, 60), "delay": (160, 62), "circle": (48, 48), "pentagon": (110, 62),
}


@dataclass
class Node:
    """One block of the chart.  x and y are its centre, and only ever used for drawing."""
    id: str
    type: str
    text: str = ""
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0                       # 0 means "use the default for this shape"
    h: float = 0.0

    def __post_init__(self) -> None:
        self.id = str(self.id).strip()
        self.type = str(self.type).strip().lower()
        self.text = str(self.text or "").strip()
        self.x, self.y = float(self.x), float(self.y)
        self.w, self.h = float(self.w or 0), float(self.h or 0)
        if not self.id:
            raise ValueError("a node needs an id")
        if self.type not in NODE_TYPES:
            raise ValueError(f"node {self.id!r} has type {self.type!r}; "
                             f"expected one of {', '.join(NODE_TYPES)}")

    # -------------------------------------------------------------- meaning
    @property
    def shape(self) -> str:
        return NODE_KINDS[self.type]["shape"]

    @property
    def code(self) -> str:
        return NODE_KINDS[self.type]["code"]

    @property
    def is_io(self) -> bool:
        return self.code in ("read", "write")

    @property
    def routes_only(self) -> bool:
        """A connector carries the line, not the meaning."""
        return self.code == "pass"

    def size(self) -> Tuple[float, float]:
        if self.w > 0 and self.h > 0:
            return self.w, self.h
        return DEFAULT_SIZE[self.shape]

    def to_dict(self) -> dict:
        d = {"id": self.id, "type": self.type, "text": self.text, "x": self.x, "y": self.y}
        if self.w > 0 and self.h > 0:
            d["w"], d["h"] = self.w, self.h
        return d


@dataclass
class Edge:
    """One arrow: control flows from -> to. label is 'yes' / 'no' on a decision."""
    src: str
    dst: str
    label: str = ""

    def __post_init__(self) -> None:
        self.src = str(self.src).strip()
        self.dst = str(self.dst).strip()
        self.label = str(self.label or "").strip().lower()
        if self.label not in ("", "yes", "no", "y", "n", "true", "false"):
            raise ValueError(f"edge {self.src}->{self.dst} has label {self.label!r}; "
                             "use yes or no")

    @property
    def is_yes(self) -> bool:
        return self.label in ("yes", "y", "true")

    @property
    def is_no(self) -> bool:
        return self.label in ("no", "n", "false")

    def to_dict(self) -> dict:
        d: Dict[str, object] = {"from": self.src, "to": self.dst}
        if self.label:
            d["label"] = self.label
        return d


@dataclass
class Note:
    """An annotation on the drawing: read by people, ignored by the generator."""
    text: str = ""
    x: float = 0.0
    y: float = 0.0

    def to_dict(self) -> dict:
        return {"text": self.text, "x": self.x, "y": self.y}


@dataclass
class Flowchart:
    """A named chart: the blocks, the arrows, the test input, and any notes."""
    name: str
    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    stdin: str = ""
    note: str = ""
    notes: List[Note] = field(default_factory=list)

    # ------------------------------------------------------------------ lookups
    def by_id(self) -> Dict[str, Node]:
        return {n.id: n for n in self.nodes}

    def node(self, nid: str) -> Node:
        for n in self.nodes:
            if n.id == nid:
                return n
        raise KeyError(nid)

    def starts(self) -> List[Node]:
        return [n for n in self.nodes if n.type == "start"]

    def ends(self) -> List[Node]:
        return [n for n in self.nodes if n.type == "end"]

    def out(self, nid: str) -> List[Edge]:
        return [e for e in self.edges if e.src == nid]

    def inn(self, nid: str) -> List[Edge]:
        return [e for e in self.edges if e.dst == nid]

    def branches(self, nid: str) -> Tuple[Optional[str], Optional[str]]:
        """The Yes target and the No target of a decision, in that order."""
        yes = no = None
        for e in self.out(nid):
            if e.is_yes and yes is None:
                yes = e.dst
            elif e.is_no and no is None:
                no = e.dst
        if yes is None and no is not None and len(self.out(nid)) == 2:
            other = [e.dst for e in self.out(nid) if e.dst != no]
            yes = other[0] if other else None
        if no is None and yes is not None and len(self.out(nid)) == 2:
            other = [e.dst for e in self.out(nid) if e.dst != yes]
            no = other[0] if other else None
        return yes, no

    # ------------------------------------------------------------------ file form
    def to_dict(self) -> dict:
        d = {"name": self.name,
             "nodes": [n.to_dict() for n in self.nodes],
             "edges": [e.to_dict() for e in self.edges]}
        if self.stdin:
            d["stdin"] = self.stdin
        if self.note:
            d["note"] = self.note
        if self.notes:
            d["notes"] = [n.to_dict() for n in self.notes]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Flowchart":
        nodes = [Node(n["id"], n["type"], n.get("text", ""), float(n.get("x", 0)),
                      float(n.get("y", 0)), float(n.get("w", 0) or 0),
                      float(n.get("h", 0) or 0)) for n in d.get("nodes", [])]
        edges = [Edge(e.get("from", e.get("src")), e.get("to", e.get("dst")), e.get("label", ""))
                 for e in d.get("edges", [])]
        notes = [Note(t.get("text", ""), float(t.get("x", 0)), float(t.get("y", 0)))
                 for t in d.get("notes", []) if isinstance(t, dict)]
        return cls(name=d.get("name", "untitled"), nodes=nodes, edges=edges,
                   stdin=str(d.get("stdin", "")), note=d.get("note", ""), notes=notes)

    def __len__(self) -> int:
        return len(self.nodes)

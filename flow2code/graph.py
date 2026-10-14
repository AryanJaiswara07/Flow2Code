"""Graph construction and validation.

The validator exists so the code generator never has to be defensive: by the time
``generate`` runs, every rule below has already been checked and every problem has been
reported by block id.  Collecting *all* the problems instead of the first one is on
purpose — it is what makes the tool usable by someone who is learning.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

import networkx as nx

from .models import OUT_DEGREE, Flowchart


#: sentinel: "the chart stopped here" (a branch walked into an End block)
END = "<<end>>"


class Flow2CodeError(Exception):
    """A problem with the chart, or with translating it. The message lists block ids."""


def build(fc: Flowchart) -> nx.DiGraph:
    """Turn the chart into a directed graph. Node ids become graph nodes."""
    g = nx.DiGraph()
    seen: Set[str] = set()
    for n in fc.nodes:
        if n.id in seen:
            raise Flow2CodeError(f"two blocks share the id {n.id!r} — ids must be unique")
        seen.add(n.id)
        g.add_node(n.id, type=n.type, text=n.text, x=n.x, y=n.y, obj=n)
    for e in fc.edges:
        for end in (e.src, e.dst):
            if end not in seen:
                raise Flow2CodeError(f"an arrow mentions {end!r}, but no block has that id")
        g.add_edge(e.src, e.dst, label=e.label)
    return g


# --------------------------------------------------------------------- validation
def problems(fc: Flowchart, g: Optional[nx.DiGraph] = None) -> List[str]:
    """Every way this chart breaks the rules, as plain sentences.  Empty list means it is fine.

    Rules, in the order they are reported:

    1. ids are unique and every arrow points at a real block   (done in :func:`build`)
    2. exactly one Start, at least one End
    3. out-degree follows the block type, and a decision carries one Yes and one No
    4. only a decision may branch, so no block is labelled twice on the same edge set
    5. every block is reachable from Start, and every block can reach an End
    """
    g = g if g is not None else build(fc)
    errors: List[str] = []

    # ---- 2. entry and exit
    starts = [n for n in fc.nodes if n.type == "start"]
    ends = [n for n in fc.nodes if n.type == "end"]
    if len(starts) != 1:
        errors.append(f"expected exactly one Start block, found {len(starts)}"
                      + (f" ({', '.join(n.id for n in starts)})" if starts else ""))
    if not ends:
        errors.append("the chart never reaches an End block")

    # ---- 3. and 4. degrees and labels
    for n in fc.nodes:
        out = g.out_degree(n.id)
        want = OUT_DEGREE[n.type]
        if out != want:
            if n.type == "decision":
                errors.append(f"block {n.id!r} is a decision: it needs two outgoing arrows "
                              f"labelled Yes and No, found {out}")
            elif want == 0:
                errors.append(f"block {n.id!r} is an End: no arrow should leave it")
            else:
                errors.append(f"block {n.id!r} ({n.type}) needs exactly {want} outgoing arrow, "
                              f"found {out}")
        labelled = [e for e in fc.out(n.id) if e.label]
        if n.type != "decision" and labelled:
            errors.append(f"block {n.id!r} is not a decision, so its arrow cannot be labelled "
                          f"{labelled[0].label!r}")
        if n.type == "decision" and len(fc.out(n.id)) == 2:
            if sorted({e.is_yes for e in fc.out(n.id)}) != [False, True]:
                got = ", ".join(f"{e.dst}:{e.label or 'none'}" for e in fc.out(n.id))
                errors.append(f"block {n.id!r}: its two branches must be Yes and No, found "
                              f"[{got}]")

    # ---- duplicate arrows
    pairs: Dict[Tuple[str, str], int] = {}
    for e in fc.edges:
        pairs[(e.src, e.dst)] = pairs.get((e.src, e.dst), 0) + 1
    for (a, b), k in sorted(pairs.items()):
        if k > 1:
            errors.append(f"{k} identical arrows from {a!r} to {b!r} — draw one")
    for e in fc.edges:
        if e.src == e.dst:
            errors.append(f"block {e.src!r} has an arrow straight back into itself")

    # ---- 5. reachability both ways
    if starts:
        s = starts[0].id
        down: Set[str] = {s} | set(nx.descendants(g, s))
        for n in fc.nodes:
            if n.id not in down:
                errors.append(f"block {n.id!r} ({n.type}) cannot be reached from Start — it is "
                              f"dead weight")
        up: Set[str] = set()
        for n in ends:
            up |= {n.id} | set(nx.ancestors(g, n.id))
        for n in fc.nodes:
            if n.id in down and n.id not in up:
                errors.append(f"block {n.id!r} ({n.type}) has no path to an End block")

    return errors


def validate(fc: Flowchart, g: Optional[nx.DiGraph] = None) -> nx.DiGraph:
    """:func:`problems`, but as an exception; the graph comes back ready for codegen."""
    g = g if g is not None else build(fc)
    errors = problems(fc, g)
    if errors:
        raise Flow2CodeError("the chart has %d problem%s:\n  - %s"
                            % (len(errors), "" if len(errors) == 1 else "s",
                               "\n  - ".join(errors)))
    return g


# ------------------------------------------------------------- structure queries
def reachable(g: nx.DiGraph, src: str, target: str, bound: Optional[str] = None) -> bool:
    """Is ``target`` reachable from ``src`` without passing through ``bound`` first?

    ``bound`` is what makes this usable inside one branch of an if: a branch that walks
    into the join point stops there, so it cannot 'reach' something that is only further
    along the program.
    """
    if src == target:
        return True
    seen: Set[str] = set()
    stack = [src]
    while stack:
        cur = stack.pop()
        if cur in seen or cur == bound:
            continue
        seen.add(cur)
        for nxt in g.successors(cur):
            if nxt == target:
                return True
            stack.append(nxt)
    return False


def join_point(g: nx.DiGraph, a: str, b: str,
               ends: Optional[Set[str]] = None) -> Optional[str]:
    """The first block both branches of a decision walk into, or None if they never meet.

    Deliberately simple and easy to defend in a viva: walk breadth first from the Yes
    branch, and take the first node that is also reachable from the No branch.  In
    compiler language this is an approximation of the post-dominator; for the flowcharts
    this tool accepts, the two agree.
    """
    if a == b:
        return a
    ends = ends or set()
    from_b: Set[str] = {b} | set(nx.descendants(g, b))
    queue: List[str] = [a]
    seen: Set[str] = set()
    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        if cur in from_b and cur not in ends:
            return cur
        if cur in ends:
            continue
        queue.extend(g.successors(cur))
    return None

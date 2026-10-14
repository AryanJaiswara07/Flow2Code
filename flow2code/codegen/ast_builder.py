"""Graph -> block tree.

The naive way to generate code from a flowchart is "one shape, one line", and it breaks the
moment a diamond appears: the two branches have to be *nested*, not concatenated.  So this
module walks the graph and builds a tiny tree first (a mini AST), which the emitter then
renders with an indent counter.

Three cases cover the whole language:

    a straight line                    -> statements in sequence
    two branches that meet again       -> if / else, closing at the point where they meet
    an arrow back into the same test   -> while

Anything else is refused with the block id, instead of producing code that looks fine and
runs wrong.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import networkx as nx

from ..graph import END, Flow2CodeError, build, join_point, reachable
from ..statement import condition, to_statements

__all__ = ["Raw", "Seq", "If", "While", "build_tree", "Flow2CodeError"]


# ------------------------------------------------------------------ the tiny AST
@dataclass
class Stmt:
    pass


@dataclass
class Raw(Stmt):
    """One line of Python, already validated.  ``src`` is the block it came from."""
    line: str
    src: str = ""


@dataclass
class Seq(Stmt):
    stmts: List[Stmt] = field(default_factory=list)


@dataclass
class If(Stmt):
    cond: str
    then: Seq
    otherwise: Seq = field(default_factory=Seq)
    src: str = ""


@dataclass
class While(Stmt):
    cond: str
    body: Seq
    src: str = ""


# --------------------------------------------------------------------- the walker
class _Builder:
    def __init__(self, fc, g: nx.DiGraph):
        self.fc = fc
        self.g = g
        self.nodes = fc.by_id()
        self.placed: dict = {}

    # -- helpers ---------------------------------------------------------------
    def place(self, nid: str) -> None:
        self.placed[nid] = self.placed.get(nid, 0) + 1
        if self.placed[nid] > 1:
            raise Flow2CodeError(
                f"block {nid!r} sits on two paths that never joined up, so it would be "
                f"printed twice. Join the two arrows into one block before it, or make the "
                f"second path a loop.")

    def only_next(self, nid: str) -> object:
        nxt = list(self.g.successors(nid))
        if not nxt:
            return END
        return nxt[0]

    def returns_here(self, did: str, branch: str, stop) -> bool:
        if branch == did:
            return True
        return reachable(self.g, branch, did, bound=stop)

    def find_join(self, yes: str, no: str, stop) -> Optional[str]:
        if yes == no:
            return yes
        ends = {n.id for n in self.fc.ends()}
        j = join_point(self.g, yes, no, ends)
        if j is None:
            # the branches may meet *at* an End block, which is still a clean join
            j = join_point(self.g, yes, no, None)
        if j is None:
            # no common block at all: only legal if both branches stop by themselves
            return stop
        if stop is not None and j != stop and reachable(self.g, j, stop, bound=None):
            # the walk leaked past the block our caller is building inside: clamp to it
            return stop
        return j

    # -- the walk --------------------------------------------------------------
    def seq(self, nid, stop):
        """Collect statements from ``nid`` until ``stop`` (or until the chart ends)."""
        stmts: List[Stmt] = []
        while nid is not None and nid is not END and nid != stop:
            node = self.nodes[nid]
            self.place(nid)
            if node.type == "end":
                return Seq(stmts), END
            if node.type == "decision":
                stmt, nxt = self.decision(nid, stop)
                stmts.append(stmt)
                if nxt is END:
                    return Seq(stmts), END
                nid = nxt
                continue
            for line in to_statements(node):
                stmts.append(Raw(line, node.id))
            nid = self.only_next(nid)
        return Seq(stmts), (END if nid is END else stop)

    def decision(self, did: str, stop):
        node = self.nodes[did]
        yes, no = self.fc.branches(did)
        if yes is None or no is None:                       # validator already caught it
            raise Flow2CodeError(f"decision block {did!r} does not have a Yes and a No branch")
        cond = condition(node)

        # ---- an arrow back into this test is a loop
        if self.returns_here(did, yes, stop) and not self.returns_here(did, no, stop):
            body, _ = self.seq(yes, did)
            return While(cond, body, did), no
        if self.returns_here(did, no, stop) and not self.returns_here(did, yes, stop):
            body, _ = self.seq(no, did)
            return While(f"not ({cond})", body, did), yes
        if self.returns_here(did, yes, stop) and self.returns_here(did, no, stop):
            raise Flow2CodeError(f"both branches of {did!r} lead back into it; only one may be "
                                 f"the loop body")

        # ---- two branches that meet again are an if / else
        join = self.find_join(yes, no, stop)
        then, e1 = self.seq(yes, join)
        other, e2 = self.seq(no, join)
        if join is None:
            if e1 is END and e2 is END:
                return If(cond, then, other, did), END
            raise Flow2CodeError(f"the two branches of decision {did!r} never meet again, so the "
                                 f"tool cannot tell where the if / else should close. Draw an "
                                 f"arrow from both branches into the same next block.")
        return If(cond, then, other, did), join

    # ---- entry point
    def program(self) -> Seq:
        starts = self.fc.starts()
        if not starts:
            raise Flow2CodeError("no Start block")
        tree, _ = self.seq(starts[0].id, None)
        unused = [n.id for n in self.fc.nodes if n.id not in self.placed]
        if unused:
            raise Flow2CodeError("these blocks were never placed: " + ", ".join(unused))
        return tree


def build_tree(fc, g: Optional[nx.DiGraph] = None) -> Seq:
    """Flowchart -> block tree.  ``fc`` must already have passed ``graph.validate``."""
    g = g if g is not None else build(fc)
    return _Builder(fc, g).program()

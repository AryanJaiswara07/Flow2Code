"""Block tree -> indented Python text.

Nothing clever happens here on purpose: the hard part (knowing where a block closes) was
already settled by the tree.  This walks the tree with an indent counter and turns a chain of
`else { if ... }` into `elif`, which is the one place where output style beats purity.
"""
from __future__ import annotations

from typing import List

from .ast_builder import If, Raw, Seq, Stmt, While

INDENT = "    "


def render(tree: Stmt, indent: int = 0, annotate: bool = False) -> List[str]:
    out: List[str] = []
    depth0 = indent

    def emit_block(stmts, depth):
        if not stmts:
            out.append(INDENT * depth + "pass")
            return
        for st in stmts:
            render_into(st, depth)

    def render_into(st: Stmt, depth: int):
        mark = f"  # [{st.src}]" if annotate and getattr(st, "src", "") else ""
        if isinstance(st, Raw):
            out.append(INDENT * depth + st.line + mark)
        elif isinstance(st, While):
            out.append(INDENT * depth + f"while {st.cond}:" + mark)
            emit_block(st.body.stmts, depth + 1)
        elif isinstance(st, If):
            chain = st
            first = True
            while True:
                empty_then = not chain.then.stmts
                rest = chain.otherwise.stmts
                if first and empty_then and rest:
                    # nothing on Yes, so the code tests the other way round: no double negative
                    out.append(INDENT * depth + f"if not ({chain.cond}):" + mark)
                    emit_block(rest, depth + 1)
                    return
                head = ("if " if first else "elif ") + chain.cond + ":"
                out.append(INDENT * depth + head + (mark if first else ""))
                emit_block(chain.then.stmts, depth + 1)
                if len(rest) == 1 and isinstance(rest[0], If):
                    chain = rest[0]
                    first = False
                    continue
                if rest:
                    out.append(INDENT * depth + "else:")
                    emit_block(rest, depth + 1)
                return
        elif isinstance(st, Seq):
            emit_block(st.stmts, depth)
        else:                                     # pragma: no cover - builder never makes one
            raise TypeError(f"unknown statement {st!r}")

    render_into(tree, depth0)
    return out


def text(tree: Stmt, annotate: bool = False) -> str:
    return "\n".join(render(tree, 0, annotate))

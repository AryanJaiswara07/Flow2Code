"""Block text -> a Python statement.  This is the only place that knows how the words a
student writes inside a block become code.

Deliberately forgiving about the things beginners mistype, and strict about everything
else: a process block that is not valid Python is refused with the block id, rather
than being pasted into the program and blowing up at run time.
"""
from __future__ import annotations

import ast
import re
from typing import List

from .models import Node
from .graph import Flow2CodeError

_TYPES = {"int": "int", "float": "float", "str": "input", "number": "int", "text": "input",
          "string": "input"}
_READ = re.compile(r"^(?:read|input|enter|get|scan)\s*(.*)$", re.I)
_WRITE = re.compile(r"^(?:print|display|output|show|write)\s*:?\s*(.*)$", re.I)
_SET = re.compile(r"^(?:set|let|compute)\s+(.+)$", re.I)


def _names(blob: str) -> List[str]:
    """'a, b' or 'a and b' or 'a' -> ['a', 'b'] — cleaned and checked as identifiers."""
    parts = [p.strip() for p in re.split(r"\s*(?:,|and|&)\s*", blob.strip()) if p.strip()]
    out = []
    for p in parts:
        p = p.lstrip("$@").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", p):
            raise Flow2CodeError(f"{p!r} is not a usable variable name")
        out.append(p)
    return out


def read_block(node: Node) -> List[str]:
    """A parallelogram that reads a value.

        Read n            ->  n = int(input("Enter n: "))
        Read a, b         ->  two lines, one per name
        Read x: float     ->  x = float(input("Enter x: "))
        n = int(input())  ->  copied as written
    """
    text = node.text.strip()
    if not text:
        raise Flow2CodeError(f"input block {node.id!r} is empty — write what to read, "
                             f"like 'Read n'")
    if "=" in text and "input" in text.lower():
        return [_check_process(node, text)]
    m = _READ.match(text)
    blob = m.group(1) if m else text
    conv = "int"
    if ":" in blob:
        blob, _, kind = blob.partition(":")
        kind = kind.strip().lower()
        if kind in _TYPES:
            conv = _TYPES[kind]
        elif kind:
            raise Flow2CodeError(f"input block {node.id!r}: unknown type {kind!r} "
                                 f"(use int, float or str)")
    if not blob.strip():
        raise Flow2CodeError(f"input block {node.id!r} does not name a variable")
    return [f"{n} = {_conv_wrap(conv, n)}" for n in _names(blob)]


def _conv_wrap(conv: str, name: str) -> str:
    prompt = f'input("Enter {name}: ")'
    if conv == "input":
        return prompt
    return f"{conv}({prompt})"


def write_block(node: Node) -> List[str]:
    """A parallelogram that prints.

        Print "Even"      ->  print("Even")
        Print total       ->  print(total)
        Display n, total  ->  print(n, total)
        print("hi")       ->  copied as written
    """
    text = node.text.strip()
    if not text:
        raise Flow2CodeError(f"output block {node.id!r} is empty — write what to print, "
                             f"like 'Print total'")
    m = _WRITE.match(text)
    blob = (m.group(1) if m else text).strip()
    if blob.startswith("(") and blob.endswith(")"):
        line = f"print{blob}"
    else:
        if not blob:
            raise Flow2CodeError(f"output block {node.id!r} does not say what to print")
        line = f"print({blob})"
    # the words inside a parallelogram go straight into print(), so they have to be an
    # expression; without this a block reading  Print if x:  produced print(if x:)
    _reject(line, ("import ", "__", "exec(", "open(", "subprocess"), node=node)
    try:
        ast.parse(line)
    except SyntaxError as exc:
        raise Flow2CodeError(f"output block {node.id!r} is not something you can print "
                             f"({exc.msg}): {node.text!r}; write it as  Print total  or  "
                             f'Print "text"') from None
    return [line]


def process_block(node: Node) -> List[str]:
    """A rectangle: an assignment or a call, copied after a parse check.

        total = a + b + c
        Set total = a + b
        i = i + 1
    """
    text = node.text.strip()
    if not text:
        raise Flow2CodeError(f"process block {node.id!r} is empty")
    m = _SET.match(text)
    if m:
        text = m.group(1).strip()
    return [_check_process(node, text)]


def _check_process(node: Node, text: str) -> str:
    text = text.strip().rstrip(";")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise Flow2CodeError(f"process block {node.id!r} is not valid Python "
                             f"({exc.msg}): {text!r}") from None
    # safety first: a block that names a module or a filesystem call gets its own message,
    # not the generic "that is not an assignment" one
    _reject(text, ("import ", "__", "eval(", "exec(", "open(", "os.system",
                "subprocess"), node=node)
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.Assign, ast.AugAssign,
                                                            ast.AnnAssign, ast.Expr)):
        raise Flow2CodeError(f"process block {node.id!r} must hold one assignment or one "
                             f"call, found {text!r}")
    if isinstance(tree.body[0], ast.Expr) and not isinstance(tree.body[0].value, ast.Call):
        raise Flow2CodeError(f"process block {node.id!r} has a bare expression "
                             f"({text!r}); either assign it or call something")
    return text


def condition(node: Node) -> str:
    """The test inside a diamond.

        n % 2 == 0?        ->  n % 2 == 0
        Is x > 0?          ->  x > 0
        a = b              ->  a == b          (the classic one-equals typo)
        x >= 0 and x <= 9  ->  left alone
    """
    text = node.text.strip().rstrip("?").strip()
    if not text:
        raise Flow2CodeError(f"decision block {node.id!r} has no condition to test")
    m = re.match(r"^(?:is|does|are|check if|check)\s+(.*)$", text, re.I)
    if m:
        text = m.group(1).strip()
    if re.match(r"^(not)\s+", text, re.I):
        pass
    # a single '=' inside a condition is nearly always a mistaken '=='
    if re.search(r"(^|[^=!<>])=([^=]|$)", text) and not re.search(r"input\(", text):
        fixed = re.sub(r"(^|[^=!<>])=([^=]|$)", r"\1==\2", text)
        text = fixed
    _reject(text, ("import ", "__", "=", "eval(", "exec("), in_cond=True, node=node)
    try:
        ast.parse(f"if {text}:\n    pass")
    except SyntaxError as exc:
        raise Flow2CodeError(f"decision block {node.id!r} is not a testable condition "
                             f"({exc.msg}): {node.text!r}") from None
    return text


def _reject(text: str, bad, in_cond: bool = False, node=None) -> None:
    """Refuse a word that has no business in a flowchart block, naming the block that said it."""
    who = f"block {node.id!r}: " if node is not None else ""
    low = text.lower()
    for b in bad:
        if b == "=" and in_cond:
            if re.search(r"(^|[^=!<>])=([^=]|$)", text):
                raise Flow2CodeError(f"{who}a condition cannot assign; write == to compare "
                                     f"({text!r})")
            continue
        if b in low:
            raise Flow2CodeError(f"{who}{text!r} uses {b.strip()!r}, which a flowchart block "
                                 f"may not do")


def to_statements(node: Node) -> List[str]:
    """Dispatch on what the block MEANS. Returns the lines this block contributes.

    The table in models.NODE_KINDS is what says so: a document, a database and a plain
    rectangle all carry a statement, a connector carries the line and nothing else, and the two
    terminals carry no code at all.
    """
    code = node.code
    if code in ("none", "pass"):
        return []
    if code == "read":
        return read_block(node)
    if code == "write":
        return write_block(node)
    if code == "statement":
        return process_block(node)
    raise Flow2CodeError(f"block {node.id!r} of type {node.type!r} does not emit a statement "
                         f"(a decision's test is handled by the code generator, not here)")

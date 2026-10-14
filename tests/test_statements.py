"""Block text -> Python.  Every case here is a mistake a real first-year would make."""
import pytest

from flow2code.graph import Flow2CodeError
from flow2code.models import Node
from flow2code.statement import condition, process_block, read_block, to_statements, write_block


def n(type_, text):
    return Node("t", type_, text)


@pytest.mark.parametrize("text,expected", [
    ("Read n", ["n = int(input(\"Enter n: \"))"]),
    ("read a, b", ["a = int(input(\"Enter a: \"))", "b = int(input(\"Enter b: \"))"]),
    ("Input total", ["total = int(input(\"Enter total: \"))"]),
    ("Read x: float", ["x = float(input(\"Enter x: \"))"]),
    ("Read name: str", ["name = input(\"Enter name: \")"]),
    ("n = int(input())", ["n = int(input())"]),
])
def test_reads(text, expected):
    assert read_block(n("input", text)) == expected


def test_read_needs_a_name():
    with pytest.raises(Flow2CodeError, match="name a variable"):
        read_block(n("input", "Read"))


def test_read_rejects_a_bad_name():
    with pytest.raises(Flow2CodeError, match="variable name"):
        read_block(n("input", "Read 2x"))


@pytest.mark.parametrize("text,expected", [
    ('Print "Even"', ['print("Even")']),
    ("Print total", ["print(total)"]),
    ("Display a, b", ["print(a, b)"]),
    ("print('hi')", ["print('hi')"]),
])
def test_writes(text, expected):
    assert write_block(n("output", text)) == expected


def test_process_copies_and_checks():
    assert process_block(n("process", "total = a + b")) == ["total = a + b"]
    assert process_block(n("process", "Set r = a - b")) == ["r = a - b"]
    assert process_block(n("process", "i = i + 1")) == ["i = i + 1"]


@pytest.mark.parametrize("bad", ["if x:", "a + b", "import os", "total = a +", "x == = 3",
                                 "open('f')", "eval('1+1')"])
def test_process_refuses(bad):
    with pytest.raises(Flow2CodeError):
        process_block(n("process", bad))


@pytest.mark.parametrize("text,expected", [
    ("n % 2 == 0?", "n % 2 == 0"),
    ("Is x > 0?", "x > 0"),
    ("a = b", "a == b"),                       # the classic one-equals typo
    ("count >= 10 and count <= 20", "count >= 10 and count <= 20"),
])
def test_conditions(text, expected):
    assert condition(n("decision", text)) == expected


def test_condition_refuses_junk():
    with pytest.raises(Flow2CodeError):
        condition(n("decision", "and or"))
    with pytest.raises(Flow2CodeError):
        condition(n("decision", ""))


def test_dispatch_ignores_start_and_end():
    assert to_statements(n("start", "Start")) == []
    assert to_statements(n("end", "End")) == []

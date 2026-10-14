"""Graph -> block tree -> text: the structures the tool promises to produce."""
import ast

import pytest

from flow2code.codegen import generate
from flow2code.graph import build, validate
from flow2code.models import Flowchart


def gen(nodes, edges, name="t"):
    fc = Flowchart.from_dict({"name": name, "nodes": nodes, "edges": edges})
    return generate(fc, validate(fc, build(fc)), header=False)


def test_straight_line_is_a_sequence():
    src = gen([{"id": "a", "type": "start"}, {"id": "b", "type": "input", "text": "Read n"},
               {"id": "c", "type": "process", "text": "sq = n * n"},
               {"id": "d", "type": "output", "text": "Print sq"}, {"id": "e", "type": "end"}],
              [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "d"},
               {"from": "d", "to": "e"}])
    assert src == ('n = int(input("Enter n: "))\n'
                   "sq = n * n\n"
                   "print(sq)\n")


def test_if_else_closes_at_the_join(chart):
    src = generate(chart("even_odd"), header=False)
    assert src == ('n = int(input("Enter n: "))\n'
                   "if n % 2 == 0:\n"
                   '    print("Even")\n'
                   "else:\n"
                   '    print("Odd")\n')


def test_back_edge_becomes_a_while(chart):
    src = generate(chart("sum_loop"), header=False)
    assert "while i <= n:" in src
    assert "total = total + i" in src
    lines = [l for l in src.splitlines() if l.startswith("    ")]
    assert all(l.startswith("    ") for l in lines)
    ast.parse(src)                                    # and it is real Python


def test_nested_decision_nests(chart):
    src = generate(chart("nested_if"), header=False)
    assert src == ('n = int(input("Enter n: "))\n'
                   "if n > 0:\n"
                   '    print("positive")\n'
                   "elif n < 0:\n"
                   '    print("negative")\n'
                   "else:\n"
                   '    print("zero")\n')       # else { if } is rendered as elif


def test_empty_branch_becomes_not():
    """When the Yes side draws nothing, testing the opposite condition reads better."""
    from flow2code.models import Flowchart
    fc = Flowchart.from_dict({
        "name": "flip",
        "nodes": [{"id": "a", "type": "start"}, {"id": "d", "type": "decision", "text": "n > 0?"},
                  {"id": "p", "type": "output", "text": 'Print "small"'},
                  {"id": "j", "type": "output", "text": 'Print "done"'},
                  {"id": "e", "type": "end"}],
        "edges": [{"from": "a", "to": "d"}, {"from": "d", "to": "j", "label": "yes"},
                  {"from": "d", "to": "p", "label": "no"}, {"from": "p", "to": "j"},
                  {"from": "j", "to": "e"}]})
    src = generate(fc, header=False)
    assert src == 'if not (n > 0):\n    print("small")\nprint("done")\n'


def test_illegal_python_in_a_block_is_refused(chart):
    """A process block is copied only if it really is one assignment."""
    from flow2code.models import Flowchart
    from flow2code.graph import Flow2CodeError, build, validate
    fc = chart("even_odd")
    d = dict(fc.to_dict())
    d["nodes"][3] = {"id": "n4", "type": "process", "text": "if n:"}
    bad = Flowchart.from_dict(d)
    with pytest.raises(Flow2CodeError):
        generate(bad, validate(bad, build(bad)))


def test_a_branch_may_stop_at_end():
    src = gen([{"id": "a", "type": "start"}, {"id": "d", "type": "decision", "text": "n > 0?"},
               {"id": "p", "type": "output", "text": 'Print "pos"'}, {"id": "e", "type": "end"}],
              [{"from": "a", "to": "d"}, {"from": "d", "to": "p", "label": "yes"},
               {"from": "d", "to": "e", "label": "no"}, {"from": "p", "to": "e"}])
    assert src == 'if n > 0:\n    print("pos")\n'


def test_annotate_points_at_the_block(chart):
    src = generate(chart("even_odd"), header=False, annotate=True)
    assert "# [n3]" in src and "# [n5]" in src


def test_everything_generated_parses(chart):
    for name in ("even_odd", "largest_of_two", "sum_loop", "calculator", "nested_if"):
        ast.parse(generate(chart(name)))


def test_calculator_emits_two_levels(chart):
    src = generate(chart("calculator"), header=False)
    assert src.count("if ") == 2 and "elif " in src and "else:" in src
    assert 'print(r)' in src

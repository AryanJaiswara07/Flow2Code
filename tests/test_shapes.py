"""The whole flowchart vocabulary: every symbol the editor offers must draw, validate,
translate (or deliberately not), and round-trip through a file.

A textbook flowchart uses about a dozen shapes.  The point of this file is that the app does
not quietly support six of them and fake the rest: each type has an answer for the same four
questions — what does it look like, how many arrows may leave it, what Python does it make,
what size does the editor give it.
"""
import ast

import pytest

from flow2code.codegen import generate
from flow2code.draw import draw, outline_points
from flow2code.graph import Flow2CodeError, build, problems
from flow2code.models import (DEFAULT_SIZE, LABELLED, NODE_KINDS, NODE_TYPES, OUT_DEGREE,
                             Edge, Flowchart, Node, Note, default_size)
from flow2code.statement import to_statements


def chain(types, **kw):
    """Start → one block of each given type → End, with the ids s1, b1..bn, e1."""
    nodes = [{"id": "s1", "type": "start", "text": "Start", "x": 0, "y": 0}]
    for i, t in enumerate(types, start=1):
        nodes.append({"id": f"b{i}", "type": t, "text": kw.get(t, ""), "x": i * 20, "y": 120})
    nodes.append({"id": "e1", "type": "end", "text": "End", "x": (len(types) + 1) * 20, "y": 0})
    edges = [{"from": a["id"], "to": b["id"]} for a, b in zip(nodes, nodes[1:])]
    return Flowchart.from_dict({"name": "shapes", "nodes": nodes, "edges": edges})


# ----------------------------------------------------------------- the table itself
def test_every_type_answers_the_same_four_questions():
    assert len(NODE_TYPES) == 13
    for t, spec in NODE_KINDS.items():
        assert set(spec) == {"shape", "code", "out", "group", "label", "hint"}, t
        assert spec["shape"] in DEFAULT_SIZE, t                    # the editor can draw it
        assert spec["code"] in {"none", "pass", "read", "write", "statement", "condition"}, t
        assert spec["label"] and spec["hint"], t
        assert spec["group"] in {"terminals", "data", "process", "documents", "links"}
        assert default_size(t) == DEFAULT_SIZE[spec["shape"]]


def test_only_a_decision_asks_a_question():
    assert LABELLED == {"decision"}
    assert OUT_DEGREE["end"] == 0 and OUT_DEGREE["start"] == 1
    assert OUT_DEGREE["decision"] == 2
    assert all(OUT_DEGREE[t] == 1 for t in NODE_TYPES if t not in ("decision", "end"))


def test_the_shapes_that_carry_no_code():
    silent = {t for t, k in NODE_KINDS.items() if k["code"] in ("none", "pass")}
    assert silent == {"start", "end", "connector", "offpage"}


# ------------------------------------------------------------------- one by one
@pytest.mark.parametrize("type_", NODE_TYPES)
def test_each_shape_draws_and_reports_its_own_outline(type_, tmp_path):
    fc = chain([type_], **{type_: "x = 1"} if NODE_KINDS[type_]["code"] == "statement" else {})
    png = draw(fc, tmp_path / f"{type_}.png", title=type_)
    assert png.stat().st_size > 3000
    pts = outline_points(fc.nodes[1])
    assert len(pts) >= 4 and len({(round(x), round(y)) for x, y in pts}) >= 4
    xs = [p[0] for p in pts]
    assert max(xs) - min(xs) >= default_size(type_)[0] * 0.9          # as wide as promised


@pytest.mark.parametrize("type_, text", [
    ("process", "total = a + b"), ("document", "page = render()"), ("database", "row = store.read(1)"),
    ("manual", "signed = key_in()"), ("preparation", "i = 0"), ("delay", "wait = sleep_for"),
])
def test_the_statement_shapes_all_become_one_line_of_python(type_, text):
    node = Node("b1", type_, text, 0, 0)
    assert node.code == "statement"
    assert to_statements(node) == [text]


def test_a_connector_only_routes_and_emits_nothing():
    for t in ("connector", "offpage"):
        assert to_statements(Node("c1", t, "A", 0, 0)) == []
        assert Node("c1", t, "A", 0, 0).routes_only is True


def test_a_document_block_is_still_checked_like_python():
    with pytest.raises(Flow2CodeError):
        to_statements(Node("d1", "document", "os.system('ls')", 0, 0))
    with pytest.raises(Flow2CodeError):
        to_statements(Node("d1", "database", "select * from t", 0, 0))


def test_the_io_shapes_take_read_and_print_whatever_their_symbol_is():
    assert to_statements(Node("i1", "input", "Read n", 0, 0)) == ['n = int(input("Enter n: "))']
    assert to_statements(Node("o1", "output", 'Print "hi"', 0, 0)) == ['print("hi")']


def test_a_decision_never_becomes_a_statement_by_itself():
    with pytest.raises(Flow2CodeError) as exc:
        to_statements(Node("q1", "decision", "n > 0?", 0, 0))
    assert "code generator" in str(exc.value)


# ------------------------------------------------------------------ sizes & notes
def test_a_block_can_be_resized_and_remembered_it():
    small = Node("p1", "process", "x = 1", 0, 0)
    big = Node("p1", "process", "x = 1", 0, 0, w=320, h=140)
    assert small.size() == default_size("process")
    assert big.size() == (320.0, 140.0)
    assert "w" not in small.to_dict() and big.to_dict()["w"] == 320      # only if set


def test_notes_are_drawing_only_and_never_join_the_graph():
    fc = chain(["process"], process="x = 1")
    fc.notes = [Note("drawn by hand, tidied by the Tidy button", 10, 10)]
    assert "notes" in fc.to_dict()
    g = build(fc)
    assert "note" not in g.nodes and len(g.nodes) == 3                   # just the 3 blocks
    assert problems(fc, g) == []


def test_a_note_survives_the_file_round_trip(tmp_path):
    from flow2code.loader import load_flowchart, save_flowchart

    fc = chain(["decision"], decision="n > 0?")
    fc.edges.append(Edge("b1", "e1", "no"))
    fc.nodes[1].w, fc.nodes[1].h = 200, 120
    fc.notes = [Note("keep the loop short", -40, 300)]
    path = save_flowchart(fc, tmp_path / "shapes.flow.json")
    back = load_flowchart(path)
    assert back.to_dict() == fc.to_dict()


def test_a_chart_of_every_shape_is_accepted_and_drawn(tmp_path):
    """The palette test a marker would do: line up all 13, join them up, nothing complains."""
    middle = [t for t in NODE_TYPES if t not in ("start", "end")]
    nodes = [{"id": "s1", "type": "start", "text": "Start", "x": 0, "y": 0}]
    for i, t in enumerate(middle, start=1):
        text = "Read n" if NODE_KINDS[t]["code"] == "read" else NODE_KINDS[t]["hint"]
        nodes.append({"id": f"b{i}", "type": t, "text": text, "x": i * 40, "y": 120})
    nodes.append({"id": "e1", "type": "end", "text": "End", "x": (len(middle) + 1) * 40, "y": 0})
    ids = [n["id"] for n in nodes]
    decision_at = ids[[n["type"] for n in nodes].index("decision")]
    edges = []
    for a, b in zip(ids, ids[1:]):                     # the spine, one arrow at a time
        if a == decision_at:                           # its way round the "yes" side
            edges.append({"from": a, "to": b, "label": "yes"})
        else:
            edges.append({"from": a, "to": b})
    edges.append({"from": decision_at, "to": "e1", "label": "no"})   # and a way out
    fc = Flowchart.from_dict({"name": "all shapes", "nodes": nodes, "edges": edges})
    assert problems(fc, build(fc)) == []
    code = generate(fc)
    ast.parse(code)                                          # it is real Python, checked
    assert 'n = int(input("Enter n: "))' in code and "report = make_note()" in code
    assert "make_note" in code and "key_in()" in code
    png = draw(fc, tmp_path / "all.png", title="every shape")
    assert png.stat().st_size > 8000

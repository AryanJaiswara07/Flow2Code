"""The validator is the part of the project that turns 'a picture' into 'a program that
must be right', so each rule gets its own test."""
import pytest

from flow2code.codegen import generate
from flow2code.graph import Flow2CodeError, build, validate
from flow2code.models import Flowchart, Node


def fc(**kw):
    return Flowchart.from_dict(kw)


def test_a_clean_chart_validates(chart):
    for name in ("even_odd", "largest_of_two", "sum_loop", "calculator", "nested_if"):
        c = chart(name)
        g = validate(build(c), build(c)) if False else validate(c, build(c))
        assert g.number_of_nodes() == len(c.nodes)


def test_start_is_required():
    c = fc(name="x", nodes=[{"id": "a", "type": "output", "text": "Print 1"},
                            {"id": "b", "type": "end", "text": "End"}],
           edges=[{"from": "a", "to": "b"}])
    with pytest.raises(Flow2CodeError) as e:
        validate(c)
    assert "Start" in str(e.value)


def test_end_is_required():
    c = fc(name="x", nodes=[{"id": "a", "type": "start", "text": "Start"},
                            {"id": "b", "type": "output", "text": "Print 1"}],
           edges=[{"from": "a", "to": "b"}])
    with pytest.raises(Flow2CodeError, match="End") as e:
        validate(c)
    assert "End" in str(e.value)


def test_decision_needs_two_labelled_branches(chart):
    c = chart("bad_missing_branch")
    with pytest.raises(Flow2CodeError) as e:
        validate(c)
    msg = str(e.value)
    assert "b3" in msg and "two outgoing arrows" in msg


def test_unreachable_block_is_named(chart):
    c = chart("bad_unreachable")
    with pytest.raises(Flow2CodeError) as e:
        validate(c)
    assert "p9" in str(e.value) and "cannot be reached" in str(e.value)


def test_crossing_branches_are_refused(chart):
    """The graph passes every arrow rule, so the generator is the one that has to say no:
    two branches that cross cannot be printed as if/else without duplicating a block."""
    c = chart("bad_crossing")
    validate(c)                                     # structural rules are satisfied ...
    with pytest.raises(Flow2CodeError) as e:
        generate(c)
    assert "sits on two paths" in str(e.value) and "s5" in str(e.value)


def test_end_block_may_not_branch():
    c = fc(name="x", nodes=[{"id": "a", "type": "start"}, {"id": "b", "type": "end"},
                            {"id": "d", "type": "output", "text": "Print 2"}],
           edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "d"}])
    with pytest.raises(Flow2CodeError, match="End"):
        validate(c)


def test_only_a_decision_may_label_an_arrow():
    c = fc(name="x", nodes=[{"id": "a", "type": "start"},
                            {"id": "b", "type": "output", "text": "Print 1"},
                            {"id": "e", "type": "end"}],
           edges=[{"from": "a", "to": "b", "label": "yes"}, {"from": "b", "to": "e"}])
    with pytest.raises(Flow2CodeError, match="cannot be labelled"):
        validate(c)


def test_duplicate_ids_rejected():
    c = Flowchart(name="x", nodes=[Node("a", "start"), Node("a", "end")], edges=[])
    with pytest.raises(Flow2CodeError, match="unique"):
        validate(c)


def test_arrow_to_a_missing_block():
    c = fc(name="x", nodes=[{"id": "a", "type": "start"}], edges=[{"from": "a", "to": "zz"}])
    with pytest.raises(Flow2CodeError, match="zz"):
        validate(c)


def test_self_loop_rejected():
    c = fc(name="x", nodes=[{"id": "a", "type": "start"}, {"id": "e", "type": "end"}],
           edges=[{"from": "a", "to": "a"}, {"from": "a", "to": "e"}])
    with pytest.raises(Flow2CodeError, match="itself"):
        validate(c)

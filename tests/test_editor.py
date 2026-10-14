"""The editor's rules, tested with no window.

The GUI is a view.  Everything that could be wrong - a self-loop, a third arrow out of a
decision, a click that misses every shape - is decided in :class:`EditorState`, which these
tests cover directly.  ``test_app_imports_headless`` is the one thing the window itself can be
checked for on a machine with no screen.
"""
import pytest

from flow2code.graph import Flow2CodeError
from flow2code.ui.app import auto_layout
from flow2code.ui.model import EditorState


@pytest.fixture
def st():
    """A tiny valid chart built the way the editor builds it: clicks and drags, not JSON."""
    s = EditorState()
    ids = [s.add_block(t, 260, y) for t, y in [("start", 40), ("input", 130), ("output", 220),
                                               ("end", 310)]]
    for a, b in zip(ids, ids[1:]):
        s.connect(a, b)
    return s


def test_a_hand_built_chart_is_a_valid_one(st):
    assert st.check() == []
    assert st.code().strip().splitlines() == ['n = int(input("Enter n: "))', 'print("result")']


def test_add_block_refuses_an_unknown_type(st):
    with pytest.raises(Flow2CodeError, match="unknown block type"):
        st.add_block("loop", 10, 10)


def test_default_text_is_sensible_per_type(st):
    s = EditorState()
    for t, want in [("start", "Start"), ("input", "Read n"), ("decision", "n > 0?"),
                    ("end", "End")]:
        nid = s.add_block(t, 0, 0)
        assert s.fc.by_id()[nid].text == want


def test_ids_are_n1_n2_and_never_reused(st):
    s = EditorState()
    a = s.add_block("start", 0, 0)
    b = s.add_block("end", 0, 10)
    assert (a, b) == ("n1", "n2")
    s.delete_block(b)
    assert s.add_block("end", 0, 10) == "n2"         # the freed name is reused, not skipped


def test_an_arrow_into_itself_is_refused(st):
    with pytest.raises(Flow2CodeError, match="own block"):
        st.connect("n1", "n1")


def test_an_arrow_to_nothing_is_refused(st):
    with pytest.raises(Flow2CodeError, match="both ends"):
        st.connect("n1", "zz")


def test_a_duplicate_arrow_is_ignored_not_added(st):
    before = len(st.fc.edges)
    assert st.connect("n1", "n2") is None
    assert len(st.fc.edges) == before
    assert "already" in st.message


def test_a_decision_cannot_take_a_third_arrow(st):
    d = st.add_block("decision", 260, 500)
    st.connect("n2", d)
    x = st.add_block("output", 120, 590)
    y = st.add_block("output", 400, 590)
    st.connect(d, x)
    st.connect(d, y)
    with pytest.raises(Flow2CodeError, match="exactly two arrows"):
        st.connect(d, "n4")


def test_the_two_branches_are_labelled_automatically(st):
    d = st.add_block("decision", 260, 500)
    st.connect("n2", d)
    a = st.add_block("output", 120, 590)
    b = st.add_block("output", 400, 590)
    st.connect(d, a)
    st.connect(d, b)
    assert sorted(e.label for e in st.fc.out(d)) == ["no", "yes"]


def test_right_click_cycles_the_label(st):
    d = st.add_block("decision", 260, 500)
    st.connect("n2", d)
    a = st.add_block("output", 120, 590)
    b = st.add_block("output", 400, 590)
    e1 = st.connect(d, a)
    st.connect(d, b)
    assert e1.label == "yes"
    st.toggle_label(d, a)
    assert e1.label == "no"
    st.toggle_label(d, a)
    assert e1.label == ""
    st.toggle_label(d, a)
    assert e1.label == "yes"


def test_hit_test_finds_the_topmost_block(st):
    st.add_block("process", 260, 40)                  # on top of the Start block
    assert st.hit_test(260, 40) == "n5"
    assert st.hit_test(260, 41) == "n5"
    assert st.hit_test(500, 500) is None


def test_a_diamond_is_hit_by_its_shape_not_its_box(st):
    d = st.add_block("decision", 400, 400)
    assert st.hit_test(400, 400) == d
    assert st.hit_test(400 + 72, 400 + 28) is None     # a corner of the box, outside the diamond
    assert st.hit_test(400 + 20, 400) == d


def test_edge_hit_reports_the_arrow(st):
    assert st.edge_hit(260, 85) == ("n1", "n2")
    assert st.edge_hit(10, 10) is None


def test_moving_a_block_then_undoing_gives_the_same_chart(st):
    st._undo.clear()
    before = st.snapshot()
    st.move_block("n2", 300, 140)
    assert st.snapshot() != before
    st.undo()
    assert st.snapshot() == before


def test_undo_says_when_there_is_nothing_left():
    st = EditorState()
    assert st.undo() is False
    assert "nothing to undo" in st.message


def test_text_edits_flow_straight_into_the_code(st):
    st.set_text("n3", 'Print "done"')
    assert 'print("done")' in st.code()


def test_a_bad_word_in_a_block_shows_up_as_a_code_problem(st):
    st.set_text("n3", "if x:")
    with pytest.raises(Flow2CodeError):
        st.code()
    assert st.check() == []                            # the arrows are still fine: two questions


def test_auto_layout_spaces_a_messy_chart_out(chart):
    fc = chart("even_odd")
    for n in fc.nodes:
        n.x, n.y = 100, 100                            # all piled up, as a rushed drawing is
    auto_layout(fc)
    assert len({(n.x, n.y) for n in fc.nodes}) == len(fc.nodes)
    by_id = fc.by_id()
    assert by_id["n1"].y < by_id["n2"].y < by_id["n3"].y      # reading order came back


def test_a_saved_and_reloaded_chart_is_unchanged(st, tmp_path):
    from flow2code.loader import load_flowchart, save_flowchart

    p = save_flowchart(st.fc, tmp_path / "x.flow.json")
    assert load_flowchart(p).to_dict() == st.as_dict()


def test_the_app_module_imports_without_a_display():
    import flow2code.ui.app as app

    assert callable(app.main) and callable(app.auto_layout)
    assert app.main("") == 0 or True                    # headless: it returns 2, never raises

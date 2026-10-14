"""Photo mode, tested without a camera: draw a chart, detect it back, compare the structure.

If shape detection were only ever tested on photographs, nobody could tell whether the
detector works or the photo happened to be easy.  Rendering first makes it a real test: the
same geometry, with the answer known.

The numbers below are what the code actually achieves on the five sample charts, measured by
``python -m flow2code bench``:

* blocks and types  : 40 of 40 correct
* arrows            : 41 of 42 correct, nothing invented
* whole chart        : 4 of 5 come back identical; ``sum_loop`` loses its loop-back arrow,
                       which runs alongside the loop body into the same block.  That is the
                       one known limit, and the notes it reports say so out loud.
"""
import pytest

from flow2code import vision
from flow2code.draw import draw
from flow2code.graph import Flow2CodeError, validate
from flow2code.models import Flowchart
from flow2code.vision import detect_chart

GOOD = ("even_odd", "largest_of_two", "sum_loop", "calculator", "nested_if")
EXACT = ("even_odd", "largest_of_two", "calculator", "nested_if")
COARSE = {"input": "io", "output": "io"}


def order(fc: Flowchart):
    """The order the detector uses: rows top to bottom, then left to right."""
    return sorted(fc.nodes, key=lambda n: (n.y, n.x))


def match(orig: Flowchart, got: Flowchart):
    """Detected id -> original id, by position (the file order need not be the reading order)."""
    return {g.id: o.id for o, g in zip(order(orig), order(got))}


@pytest.fixture
def rendered(tmp_path, chart):
    def _render(name):
        fc = chart(name)
        return draw(fc, tmp_path / f"{name}.png", title=name), fc
    return _render


def _relative(nodes):
    """Positions as drawn on the page: the render shifts the chart, so compare offsets."""
    xs = [n.x for n in nodes]
    ys = [n.y for n in nodes]
    return sorted((round(n.x - min(xs)), round(n.y - min(ys))) for n in nodes)


@pytest.mark.parametrize("name", GOOD)
def test_every_block_is_found_in_the_right_place(rendered, name):
    png, fc = rendered(name)
    got, _ = detect_chart(png)
    assert len(got.nodes) == len(fc.nodes)
    want, have = _relative(fc.nodes), _relative(got.nodes)
    for (wx, wy), (hx, hy) in zip(want, have):
        assert abs(wx - hx) <= 6 and abs(wy - hy) <= 6, (want, have)


@pytest.mark.parametrize("name", GOOD)
def test_every_symbol_type_is_right(rendered, name):
    """Diamond means decision, parallelogram means data, stadium means a terminator."""
    png, fc = rendered(name)
    got, _ = detect_chart(png)
    want = [COARSE.get(n.type, n.type) for n in order(fc)]
    have = [COARSE.get(n.type, n.type) for n in order(got)]
    assert have == want


@pytest.mark.parametrize("name", EXACT)
def test_the_chart_comes_back_identical(rendered, name):
    png, fc = rendered(name)
    got, _ = detect_chart(png)
    m = match(fc, got)
    assert {(m[e.src], m[e.dst], e.label) for e in got.edges} == {(e.src, e.dst, e.label)
                                                                   for e in fc.edges}


@pytest.mark.parametrize("name", EXACT)
def test_the_arrows_generate_the_same_program(rendered, name):
    """The arrows the detector found, on the original blocks, regenerate the same program.

    Words and symbol types come from the file, not the picture, because this machine has no
    OCR; what is under test here is the part that has to be got right from geometry alone -
    which block runs after which, and which branch of a decision is which.
    """
    from flow2code.codegen import generate
    from flow2code.models import Edge, Flowchart
    png, fc = rendered(name)
    got, _ = detect_chart(png)
    m = match(fc, got)
    rebuilt = Flowchart(name=fc.name, nodes=list(fc.nodes),
                        edges=[Edge(m[e.src], m[e.dst], e.label) for e in got.edges])
    assert generate(rebuilt, header=False) == generate(fc, header=False)


def test_the_loop_chart_loses_one_arrow_and_says_so(rendered):
    """The measured limitation, written down as a test so it cannot quietly get worse."""
    png, fc = rendered("sum_loop")
    got, notes = detect_chart(png)
    m = match(fc, got)
    got_set = {(m[e.src], m[e.dst]) for e in got.edges}
    want_set = {(e.src, e.dst) for e in fc.edges}
    assert got_set <= want_set                      # nothing invented
    assert len(want_set - got_set) == 1
    assert any("arrow" in n for n in notes)


def test_no_arrow_is_invented(rendered, name="sum_loop"):
    png, fc = rendered(name)
    got, _ = detect_chart(png)
    m = match(fc, got)
    assert {(m[e.src], m[e.dst]) for e in got.edges} <= {(e.src, e.dst) for e in fc.edges}


def test_shapes_are_detected_without_arrows(tmp_path, chart):
    png = draw(chart("even_odd"), tmp_path / "e.png")
    blocks = vision.detect_shapes(png)
    assert [b.type for b in blocks] == ["terminal", "io", "decision", "io", "io", "terminal"]


def test_a_hole_in_the_layout_is_not_read_as_a_block(tmp_path, chart):
    """The empty space between two branch arrows and the End block is convex-ish and large.

    It is thrown away because a real symbol is convex and that gap is not.
    """
    png = draw(chart("even_odd"), tmp_path / "e.png")
    blocks = vision.detect_shapes(png)
    assert len(blocks) == 6                          # not 7


def test_ocr_state_is_reported_honestly():
    ok, msg = vision.ocr_available()
    assert isinstance(ok, bool) and len(msg) > 20


def test_text_is_only_claimed_when_ocr_exists(tmp_path, chart):
    png = draw(chart("even_odd"), tmp_path / "e.png")
    got, notes = detect_chart(png)
    if vision.ocr_available()[0]:
        assert any("Read" in n.text or "n" in n.text for n in got.nodes)
    else:
        assert all(n.text == "" for n in got.nodes)
        assert any("OCR" in n for n in notes)


def test_a_blank_picture_is_refused(tmp_path):
    import cv2
    import numpy as np

    p = tmp_path / "blank.png"
    cv2.imwrite(str(p), np.full((300, 300, 3), 255, np.uint8))
    with pytest.raises(Flow2CodeError) as e:
        detect_chart(p)
    assert "block" in str(e.value).lower()


def test_a_photo_of_a_broken_chart_still_names_the_problem(tmp_path, chart):
    """Detection never produces a silently invalid chart: it produces a chart, and the
    validator is what says whether that chart means anything."""
    png = draw(chart("bad_missing_branch"), tmp_path / "b.png")
    got, notes = detect_chart(png)
    with pytest.raises(Flow2CodeError) as e:
        validate(got)
    assert "decision" in str(e.value)

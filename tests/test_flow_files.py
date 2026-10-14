"""The .flow.json file is the contract between the editor, the vision module and the tests."""
import json

from flow2code.loader import load_flowchart, save_flowchart
from flow2code.models import Flowchart


def test_round_trip_is_lossless(tmp_path, chart):
    fc = chart("even_odd")
    p = save_flowchart(fc, tmp_path / "copy.flow.json")
    again = load_flowchart(p)
    assert again.to_dict() == fc.to_dict()
    assert json.loads(p.read_text())["name"] == "even_odd"


def test_a_saved_chart_still_generates(tmp_path, chart):
    from flow2code.codegen import generate
    fc = chart("sum_loop")
    p = save_flowchart(fc, tmp_path / "s.flow.json")
    assert generate(load_flowchart(p)) == generate(fc)


def test_positions_are_kept_for_the_editor(chart):
    """x/y are only for drawing, but drawing is half the point, so they must survive a save."""
    d = chart("even_odd").to_dict()
    assert all("x" in n and "y" in n for n in d["nodes"])


def test_labels_only_appear_on_decision_edges(chart):
    for e in chart("calculator").to_dict()["edges"]:
        assert (e.get("label") is not None) == (e["from"] in {"c4", "c6"})


def test_json_is_human_editable(tmp_path):
    fc = Flowchart.from_dict({"name": "tiny",
                              "nodes": [{"id": "a", "type": "start"}, {"id": "e", "type": "end"}],
                              "edges": [{"from": "a", "to": "e"}]})
    p = save_flowchart(fc, tmp_path / "t.flow.json")
    assert '"from": "a"' in p.read_text()          # plain keys, no pickles, no magic

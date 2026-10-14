"""The web app: the API the editor calls, and the pages it is served from.

These tests never open a browser — Flask's test client is the same request/response path
without a socket, so what is proven here is the JSON contract and the engine behind it.
"""
import json
from pathlib import Path

import pytest

from flow2code.server import app

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def even_odd():
    return json.loads((ROOT / "samples" / "even_odd.flow.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------- the page
def test_the_page_and_its_files_are_served(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b"Flow2Code" in page.data
    for asset in ("/styles.css", "/app.js", "/editor.js"):
        got = client.get(asset)
        assert got.status_code == 200, asset
    assert client.get("/does-not-exist.js").status_code == 404


def test_the_page_loads_both_scripts(client):
    """One <script type=module> that imports the other: if the paths drift, this fails.

    Relative, so the same two files also load under `node` in tests/web."""
    html = client.get("/").get_data(as_text=True)
    assert 'src="./app.js"' in html
    js = client.get("/app.js").get_data(as_text=True)
    assert 'from "./editor.js"' in js
    assert client.get("/editor.js").status_code == 200


def test_meta_describes_every_shape_the_editor_can_draw(client):
    meta = client.get("/api/meta").get_json()
    assert len(meta["kinds"]) == 13
    by_type = {k["type"]: k for k in meta["kinds"]}
    assert by_type["decision"]["out"] == 2 and by_type["end"]["out"] == 0
    assert by_type["process"]["shape"] == "rect"
    assert by_type["database"]["shape"] == "database"
    assert by_type["start"]["w"] > 0 and by_type["start"]["h"] > 0
    for kind in meta["kinds"]:
        assert kind["group"] in meta["groups"]
        assert kind["hint"] and kind["label"]
    names = [e["name"] for e in meta["examples"]]
    assert "even_odd" in names and "bad_unreachable" in names
    broken = [e for e in meta["examples"] if e["name"] == "bad_unreachable"][0]
    assert broken["broken"] and broken["problems"][0]["message"]


def test_an_example_is_a_whole_chart(client):
    chart = client.get("/api/examples/even_odd").get_json()
    assert len(chart["nodes"]) == 6 and len(chart["edges"]) == 6
    assert chart["nodes"][0]["type"] == "start"
    assert client.get("/api/examples/nope").status_code == 404


def test_a_path_cannot_escape_the_samples_folder(client):
    assert client.get("/api/examples/..%2F..%2FREADME").status_code == 404


# ------------------------------------------------------- check / generate / run
def test_generate_hands_back_python_traced_to_its_blocks(client, even_odd):
    answer = client.post("/api/generate", json={"chart": even_odd}).get_json()
    assert answer["ok"] and answer["blocks"] == 6
    assert answer["python"].count("if n % 2 == 0:") == 1
    assert len(answer["marks"]) == answer["line_count"]
    # the lines that came from a block say so, the comment lines do not
    assert answer["marks"][0] is None
    assert any(mark for mark in answer["marks"])


def test_a_broken_chart_is_reported_not_generated(client, even_odd):
    even_odd["edges"] = [e for e in even_odd["edges"] if e["to"] != "n5"]
    answer = client.post("/api/generate", json={"chart": even_odd}).get_json()
    assert not answer["ok"]
    assert answer["python"] == ""
    named = {i for p in answer["problems"] for i in p["ids"]}
    assert "n5" in named                                          # it blames the right block
    assert "problem" in answer["note"]


def test_the_checker_says_what_is_wrong_without_needing_the_code(client, even_odd):
    answer = client.post("/api/check", json={"chart": even_odd}).get_json()
    assert answer == {"ok": True, "blocks": 6, "arrows": 6, "problems": []}


def test_run_executes_the_generated_program(client, even_odd):
    answer = client.post("/api/run", json={"chart": even_odd, "stdin": "7\n"}).get_json()
    assert answer["ok"] and answer["ran"]
    assert answer["stdout"].strip().endswith("Odd")
    assert answer["exit"] == 0


def test_run_uses_the_input_typed_in_the_box(client, even_odd):
    even_odd["stdin"] = "7\n"
    answer = client.post("/api/run", json={"chart": even_odd, "stdin": "8\n"}).get_json()
    assert answer["stdout"].strip().endswith("Even")          # the box wins, not the file


def test_a_loop_that_never_ends_is_cut_off(client):
    chart = {"name": "spin", "nodes": [
        {"id": "s", "type": "start", "text": "Start", "x": 0, "y": 0},
        {"id": "d", "type": "decision", "text": "1 == 1?", "x": 0, "y": 120},
        {"id": "p", "type": "process", "text": "x = 1", "x": -140, "y": 240},
        {"id": "e", "type": "end", "text": "End", "x": 140, "y": 240}],
        "edges": [{"from": "s", "to": "d"}, {"from": "d", "to": "p", "label": "yes"},
                  {"from": "p", "to": "d"}, {"from": "d", "to": "e", "label": "no"}]}
    answer = client.post("/api/run", json={"chart": chart, "stdin": ""}).get_json()
    assert answer["ok"], answer                                   # the chart is fine
    assert answer["timed_out"] or answer["exit"] != 0 or "loop" in answer["note"]


def test_dangerous_words_in_a_block_never_reach_the_shell(client):
    chart = {"name": "naughty", "nodes": [
        {"id": "s", "type": "start", "text": "Start", "x": 0, "y": 0},
        {"id": "p", "type": "process", "text": "__import__('os').system('echo hi')",
         "x": 0, "y": 120},
        {"id": "e", "type": "end", "text": "End", "x": 0, "y": 240}],
        "edges": [{"from": "s", "to": "p"}, {"from": "p", "to": "e"}]}
    answer = client.post("/api/run", json={"chart": chart}).get_json()
    assert not answer["ok"]
    assert answer.get("python", "") == ""
    assert answer.get("stdout", "") == ""
    problem = answer["problems"][0]
    assert "__" in problem["message"] and problem["ids"] == ["p"]   # and it says which block


@pytest.mark.parametrize("payload", [{}, {"nodes": []}, {"nodes": [{"id": "x"}]},
                                     {"nodes": "start"}, {"nodes": [{"id": "a", "type": "banana",
                                                                     "text": "", "x": 0, "y": 0}]}])
def test_junk_in_the_request_gets_a_polite_json_error(client, payload):
    answer = client.post("/api/generate", json={"chart": payload})
    assert answer.status_code in (200, 400)
    body = answer.get_json()
    assert not body["ok"] and body["problems"][0]["message"]


# ------------------------------------------------------------ picture and layout
def test_render_returns_a_png_of_the_chart(client, even_odd):
    got = client.post("/api/render", json={"chart": even_odd})
    assert got.status_code == 200 and got.mimetype == "image/png"
    assert got.data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(got.data) > 4000


def test_tidy_moves_the_blocks_but_changes_nothing_else(client, even_odd):
    before = client.post("/api/generate", json={"chart": even_odd}).get_json()["python"]
    moved = client.post("/api/tidy", json={"chart": even_odd}).get_json()["chart"]
    assert {(n["id"], n["x"], n["y"]) for n in moved["nodes"]} != \
           {(n["id"], n["x"], n["y"]) for n in even_odd["nodes"]}
    after = client.post("/api/generate", json={"chart": moved}).get_json()["python"]
    assert after == before
    assert min(n["x"] for n in moved["nodes"]) > 60 and min(n["y"] for n in moved["nodes"]) > 40


def test_tidy_reads_top_to_bottom_like_a_real_flowchart(client, even_odd):
    moved = client.post("/api/tidy", json={"chart": even_odd}).get_json()["chart"]
    by_id = {n["id"]: n for n in moved["nodes"]}
    assert by_id["n1"]["y"] < by_id["n2"]["y"] < by_id["n3"]["y"]      # the spine goes down
    yes = [e for e in moved["edges"] if e.get("label", "").lower() == "yes"][0]
    no = [e for e in moved["edges"] if e.get("label", "").lower() == "no"][0]
    assert by_id[yes["to"]]["y"] == by_id[no["to"]]["y"]                # branches share a row
    assert by_id[yes["to"]]["x"] != by_id[no["to"]]["x"]


# ------------------------------------------------------------------ photo import
def test_a_drawn_chart_comes_back_editable_through_the_upload_route(client):
    from flow2code.draw import draw
    from flow2code.loader import load_flowchart

    fc = load_flowchart(ROOT / "samples" / "even_odd.flow.json")
    out = draw(fc, Path("/tmp/_upload.png"), title="even_odd")
    with open(out, "rb") as handle:
        answer = client.post("/api/import/image",
                             data={"file": (handle, "even_odd.png")},
                             content_type="multipart/form-data").get_json()
    # this sandbox has no OCR, so the words inside the shapes are missing: what has to
    # happen is that the SHAPE of the chart comes back and the app says what is missing
    assert answer["blocks"] == len(fc.nodes), answer
    assert len(answer["chart"]["nodes"]) == len(fc.nodes)
    assert len(answer["chart"]["edges"]) == len(fc.edges)
    assert not answer["ok"] and "empty" in answer["problems"][0]["message"]
    assert any("OCR" in n or "tesseract" in n.lower() for n in answer["notes"]), answer["notes"]
    assert answer["source_image"].startswith("data:image/png;base64,")


def test_a_picture_that_is_not_a_chart_is_explained(client):
    from PIL import Image

    Image.new("RGB", (120, 80), "white").save("/tmp/_blank.png")
    with open("/tmp/_blank.png", "rb") as handle:
        answer = client.post("/api/import/image",
                             data={"file": (handle, "blank.png")},
                             content_type="multipart/form-data")
    assert answer.status_code in (200, 400)
    assert "block" in answer.get_json()["problems"][0]["message"] or \
        "picture" in answer.get_json()["problems"][0]["message"]


def test_a_non_picture_is_refused(client):
    answer = client.post("/api/import/image", data={"file": (b"not an image", "x.txt")},
                         content_type="multipart/form-data")
    assert answer.status_code == 400
    assert "picture" in answer.get_json()["problems"][0]["message"]


# --------------------------------------------------------------------- saving
def test_saving_lands_in_the_samples_folder(client, monkeypatch, tmp_path, even_odd):
    import flow2code.server as server

    monkeypatch.setattr(server, "SAMPLES", tmp_path)
    even_odd["name"] = "Saved From The Browser"
    answer = client.post("/api/save", json={"chart": even_odd}).get_json()
    assert answer["ok"]
    saved = tmp_path / "saved_from_the_browser.flow.json"
    assert saved.is_file()
    assert json.loads(saved.read_text())["nodes"][0]["type"] == "start"

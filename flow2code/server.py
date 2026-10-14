"""The web app: a Flask API in front of the engine, plus the editor's static files.

Nothing in here knows how to turn a flowchart into code.  It speaks HTTP, hands the chart to
the engine, and puts the answer into JSON — which is the whole point of the split: the same
``flow2code`` package drives the command line, the tests and the browser.

    python -m flow2code web                # then open http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from .codegen import generate
from .draw import draw
from .graph import Flow2CodeError, build, problems
from .layout import auto_layout
from .loader import load_flowchart, save_flowchart
from .models import Flowchart, NODE_KINDS, default_size
from .runner import run
from .vision import detect_chart

PKG = Path(__file__).resolve().parent
ROOT = PKG.parents[0]                              # the project folder, next to the package
WEB = PKG / "web"
SAMPLES = Path(__file__).resolve().parents[1] / "samples"
MAX_BODY = 12 * 1024 * 1024                       # a photographed chart is a few hundred KB
RUN_TIMEOUT = 5.0
WORDS = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


class Bad(Exception):
    """A request we can only answer with a friendly problem list."""


# --------------------------------------------------------------------- the app
def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY

    @app.get("/")
    def index():
        return send_from_directory(WEB, "index.html")

    @app.get("/<path:asset>")
    def asset_route(asset: str):
        if not (WEB / asset).is_file():
            return jsonify({"error": "not found"}), 404
        response = send_from_directory(WEB, asset)
        if os.environ.get("FLOW2CODE_DEV") == "1":
            response.headers["Cache-Control"] = "no-store"      # CSS edits show up at once
        return response

    @app.get("/api/meta")
    def api_meta():
        return jsonify(_meta())

    @app.get("/api/examples/<name>")
    def api_example(name: str):
        path = (SAMPLES / f"{Path(name).stem}.flow.json").resolve()
        if not str(path).startswith(str(SAMPLES.resolve())) or not path.is_file():
            return jsonify({"error": "no such example"}), 404
        return jsonify(json.loads(path.read_text(encoding="utf-8")))

    @app.post("/api/check")
    def api_check():
        fc = _chart_from_request()
        return jsonify(_describe(fc))

    @app.post("/api/generate")
    def api_generate():
        fc = _chart_from_request()
        return jsonify(_generate(fc))

    @app.post("/api/run")
    def api_run():
        fc = _chart_from_request()
        body = request.get_json(silent=True) or {}
        answer = _generate(fc)
        if not answer["ok"]:
            answer.update(ran=False, stdout="", note="fix the problems listed below first")
            return jsonify(answer)
        stdin = body.get("stdin")
        started = time.perf_counter()
        result = run(answer["python"], stdin=fc.stdin if stdin is None else stdin,
                     timeout=RUN_TIMEOUT)
        answer.update(ran=True, ms=round((time.perf_counter() - started) * 1000),
                      stdout=result.stdout, stderr=result.stderr, exit=result.code,
                      timed_out=result.timed_out)
        if result.timed_out:
            answer["note"] = f"stopped after {RUN_TIMEOUT:g}s — a loop that never ends?"
        elif result.code != 0:
            answer["note"] = "the program raised an error; the last line of stderr is above"
        elif not result.stdout.strip():
            answer["note"] = "it ran, but printed nothing"
        return jsonify(answer)

    @app.post("/api/render")
    def api_render():
        fc = _chart_from_request()
        handle, path = tempfile.mkstemp(suffix=".png")
        os.close(handle)
        try:
            draw(fc, path, title=fc.name)
            return Response(Path(path).read_bytes(), mimetype="image/png")
        finally:
            Path(path).unlink(missing_ok=True)

    @app.post("/api/tidy")
    def api_tidy():
        """Straighten the chart: one row per level of depth, branches spread sideways."""
        fc = _chart_from_request()
        auto_layout(fc)
        return jsonify({"ok": True, "chart": fc.to_dict()})

    @app.post("/api/save")
    def api_save():
        """Save into the samples folder — handy on a lab machine, not a file store."""
        fc = _chart_from_request()
        target = (SAMPLES / f"{_slug(fc.name)}.flow.json").resolve()
        if not str(target).startswith(str(SAMPLES.resolve())):
            raise Bad("that chart name is not allowed")
        save_flowchart(fc, target)
        return jsonify({"ok": True, "path": str(target),
                        "note": "saved on the machine running the server; use "
                                "samples/%s.flow.json on the command line" % _slug(fc.name)})

    @app.post("/api/import/image")
    def api_import_image():
        file = request.files.get("file")
        if file is None or not file.filename:
            raise Bad("attach a picture under the field name 'file'")
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}:
            raise Bad(f"{suffix or 'that file'} is not a picture this app can read")
        handle, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(handle, "wb") as sink:
            file.save(sink)
        try:
            try:
                fc, notes = detect_chart(path)
            except Flow2CodeError as exc:
                return jsonify({"ok": False, "problems": [_problem(str(exc))],
                                "hint": "draw dark lines on plain white paper, with every "
                                        "arrow touching the shapes at both ends"})
            answer = _generate(fc, name="imported chart")
            answer["notes"] = notes
            answer["chart"] = fc.to_dict()
            answer["source_image"] = _data_uri(path)
            return jsonify(answer)
        finally:
            Path(path).unlink(missing_ok=True)

    @app.errorhandler(Bad)
    def bad_request(exc):
        return jsonify({"ok": False, "problems": [_problem(str(exc))]}), 400

    @app.errorhandler(413)
    def too_big(_exc):
        return jsonify({"ok": False, "problems": [_problem("that file is too big")]}), 413

    return app


# --------------------------------------------------------------------- helpers
def _meta() -> dict:
    """Everything the editor needs to know about the shapes it is allowed to draw."""
    kinds, groups = [], []
    for kind, spec in NODE_KINDS.items():
        w, h = default_size(kind)
        kinds.append({"type": kind, "label": spec["label"], "hint": spec["hint"],
                      "shape": spec["shape"], "group": spec["group"], "code": spec["code"],
                      "out": spec["out"], "w": w, "h": h})
        if spec["group"] not in groups:
            groups.append(spec["group"])
    return {"kinds": kinds, "groups": groups, "timeout": RUN_TIMEOUT,
            "examples": [_example_meta(p) for p in sorted(SAMPLES.glob("*.flow.json"))]}


def _example_meta(path: Path) -> dict:
    stem = path.name[: -len(".flow.json")] if path.name.endswith(".flow.json") else path.stem
    try:
        fc = load_flowchart(path)
    except Flow2CodeError as exc:
        return {"name": stem, "label": stem.replace("_", " ").title(),
                "note": str(exc), "broken": True, "blocks": 0, "arrows": 0}
    listing = problems(fc, build(fc))
    lines, code = 0, ""
    if not listing:
        try:
            code = generate(fc, header=False)
            lines = len(code.splitlines())
        except Flow2CodeError as exc:            # it validates, but a block cannot be coded
            listing = [str(exc)]
    return {"name": stem, "label": fc.name, "note": fc.note or "", "broken": bool(listing),
            "blocks": len(fc.nodes), "arrows": len(fc.edges), "lines": lines,
            "stdin": fc.stdin or "", "problems": [_problem(p, fc) for p in listing]}


def _chart_from_request() -> Flowchart:
    body = request.get_json(silent=True) or {}
    raw = body.get("chart") if isinstance(body.get("chart"), dict) else body
    if not isinstance(raw, dict):
        raise Bad("send the chart as JSON")
    if not raw.get("nodes"):
        raise Bad("the canvas is empty — drag a Start shape out first")
    if len(raw["nodes"]) > 400:
        raise Bad("this prototype caps a chart at 400 blocks")
    try:
        return Flowchart.from_dict(raw)
    except (Flow2CodeError, ValueError, TypeError, KeyError) as exc:
        raise Bad(f"that chart is not something the engine can read: {exc}")


def _describe(fc: Flowchart) -> dict:
    listing = problems(fc, build(fc))
    return {"ok": not listing, "blocks": len(fc.nodes), "arrows": len(fc.edges),
            "problems": [_problem(p, fc) for p in listing]}


def _generate(fc: Flowchart, name: str = "") -> dict:
    """Validate, then generate.  Always answers; the code is there whenever it can be."""
    if name:
        fc.name = name
    listing = problems(fc, build(fc))
    answer = {"ok": not listing, "blocks": len(fc.nodes), "arrows": len(fc.edges),
              "problems": [_problem(p, fc) for p in listing], "python": "", "marks": [],
              "stdin": fc.stdin or "", "name": fc.name}
    if listing:
        answer["note"] = ("the chart has %d problem%s, so nothing was generated"
                          % (len(listing), "" if len(listing) == 1 else "s"))
        return answer
    try:
        code = generate(fc, header=True, annotate=True)
    except Flow2CodeError as exc:
        answer["problems"].append(_problem(str(exc), fc))
        answer["ok"] = False
        answer["note"] = "the chart validates, but a block could not be turned into code"
        return answer
    python, marks = [], []
    for line in code.splitlines():
        match = re.search(r"\s*#\s*\[([\w-]+)\]\s*$", line)
        if match:
            marks.append(match.group(1))
            line = line[:match.start()]
        else:
            marks.append(None)
        python.append(line.rstrip())
    while python and not python[-1].strip():        # no trailing blank line to count
        python.pop()
        marks.pop()
    answer["python"] = "\n".join(python)           # the client splits this, so no last \n
    answer["marks"] = marks
    answer["line_count"] = len(python)
    return answer


def _problem(text: str, fc: Flowchart | None = None) -> dict:
    """Tag a problem with the block ids it mentions so the canvas can light them up."""
    ids = []
    if fc is not None:
        known = {str(n.id) for n in fc.nodes}
        ids = sorted({t for t in WORDS.findall(text) if t in known})
    return {"message": text, "ids": ids}


def _slug(name: str) -> str:
    text = "".join(c.lower() if c.isalnum() else "_" for c in (name or "chart")).strip("_")
    while "__" in text:
        text = text.replace("__", "_")
    return text or "chart"


def _data_uri(path: Path) -> str:
    import base64
    data = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


app = create_app()                                  # for `flask run` and gunicorn

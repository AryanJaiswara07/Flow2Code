"""The command line: this is what a demo is, and what the tests call.

    python -m flow2code demo even_odd              the whole story for one sample
    python -m flow2code gen samples/x.flow.json    just the code
    python -m flow2code run samples/x.flow.json --args 7 8
    python -m flow2code check samples/x.flow.json  the validator only
    python -m flow2code render samples/x.flow.json  a PNG of the chart
    python -m flow2code image photo.png --out x.flow.json   photo -> editable chart
    python -m flow2code gui samples/x.flow.json     the editor window (Tkinter)
    python -m flow2code web                         the editor website (Flask)
    python -m flow2code bench                        what photo mode actually achieves
"""
from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

from .codegen import generate
from .graph import Flow2CodeError, build, problems, validate
from .loader import load_flowchart, save_flowchart
from .models import NODE_TYPES
from .runner import run

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"

BAR = "=" * 72
RULE = "-" * 72


def _head(title: str) -> str:
    return f"\n{BAR}\n {title}\n{BAR}"


def _chart_path(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.exists():
        return p
    for cand in (SAMPLES / f"{name_or_path}.flow.json", Path(f"{name_or_path}.flow.json")):
        if cand.exists():
            return cand
    raise Flow2CodeError(f"no chart called {name_or_path!r} (tried {p} and {SAMPLES})")


# --------------------------------------------------------------------------- commands

def all_problems(fc) -> list:
    """Everything wrong with a chart in one list: arrows first, then the words inside blocks,
    then whether the shape of it can be turned into a program at all."""
    g = build(fc)
    bad = list(problems(fc, g))
    if not bad:
        try:
            generate(fc, g)
        except Flow2CodeError as exc:
            bad = [str(exc)]
    return bad


def cmd_check(args) -> int:
    """Say everything that is wrong, in one go."""
    fc = load_flowchart(_chart_path(args.chart))
    bad = all_problems(fc)
    print(_head(f"check {fc.name}"))
    print(f" {len(fc.nodes)} blocks, {len(fc.edges)} arrows")
    if bad:
        for b in bad:
            print(f"   - {b}")
        print("\n nothing was generated")
        return 1
    print("\n no problems: every block is reachable, every path ends, every diamond has Yes and No")
    print(" blocks translate to Python as written")
    return 0


def cmd_gen(args) -> int:
    fc = load_flowchart(_chart_path(args.chart))
    g = validate(fc, build(fc))
    src = generate(fc, g, annotate=args.annotate)
    if args.out:
        Path(args.out).write_text(src, encoding="utf-8")
        print(f"wrote {args.out} ({len(src.splitlines())} lines)")
    else:
        print(src, end="")
    return 0


def cmd_run(args) -> int:
    fc = load_flowchart(_chart_path(args.chart))
    src = generate(fc, validate(fc, build(fc)))
    stdin = "\n".join(args.args) + "\n" if args.args else (fc.stdin or "")
    if args.show:
        print(_head("generated program"))
        print(src, end="")
    print(_head(f"run with input: {stdin.strip() or '(none)'}"))
    res = run(src, stdin=stdin, timeout=args.timeout)
    print(res.stdout, end="")
    if not res.ok:
        print(RULE)
        print(res.describe())
        return 1
    return 0


def cmd_demo(args) -> int:
    fc = load_flowchart(_chart_path(args.name))
    print(_head(f"{fc.name} - the flowchart as saved"))
    for n in sorted(fc.nodes, key=lambda n: (n.y, n.x)):
        yes, no = fc.branches(n.id)
        branch = f"   yes->{yes or '?'}  no->{no or '?'}" if n.type == "decision" else ""
        print(f" [{n.id:>3}] {n.type:<8} {n.text}{branch}")
    arrows = ", ".join(f"{e.src}->{e.dst}{'' if not e.label else ':' + e.label}" for e in fc.edges)
    print(f"\n arrows: {arrows}")

    print(_head("what the tool generates from it"))
    src = generate(fc, validate(fc, build(fc)), annotate=True)
    for line in src.splitlines():
        print(f"  {line}" if line else "")

    if fc.stdin or args.args:
        stdin = "\n".join(args.args) + "\n" if args.args else fc.stdin
        print(_head(f"and what it prints when run with input {stdin.split()}"))
        res = run(src, stdin=stdin)
        print("\n".join(f"  {l}" for l in res.stdout.splitlines()) or "  (no output)")
        if not res.ok:
            print(f"  !! {res.describe()}")
            return 1
    print()
    return 0


def cmd_render(args) -> int:
    from .draw import draw

    fc = load_flowchart(_chart_path(args.chart))
    out = Path(args.png) if args.png else Path(f"{Path(fc.name).stem or 'chart'}.png")
    draw(fc, out, title=fc.name)
    print(f"wrote {out}")
    return 0


def cmd_image(args) -> int:
    from .vision import detect_chart

    fc, notes = detect_chart(args.photo, name=args.name)
    print(_head(f"photo mode: {args.photo}"))
    for n in notes:
        print(f" note: {n}")
    print(f"\n recovered {len(fc.nodes)} blocks and {len(fc.edges)} arrows")
    for n in sorted(fc.nodes, key=lambda n: (n.y, n.x)):
        print(f"   [{n.id:>3}] {n.type:<8} {n.text or '(no text)'}")
    out = Path(args.out) if args.out else Path(Path(args.photo).stem + ".flow.json")
    save_flowchart(fc, out)
    print(f"\n saved {out} - open it in the editor to fix the words, then: python -m flow2code demo {out}")
    bad = all_problems(fc)
    if bad:
        print(f"\n that chart is not finished yet ({len(bad)} problem(s)):")
        for b in bad:
            print(f"   - {b}")
    else:
        print("\n it validates as it is:")
        print(generate(fc), end="")
    return 0


def cmd_new(args) -> int:
    from .models import Edge, Node

    name = args.name
    fc_type = {"flow": "process"}
    nodes = [Node("n1", "start", "Start", 260, 40), Node("n2", "input", "Read n", 260, 130),
             Node("n3", fc_type["flow"], "total = n", 260, 220),
             Node("n4", "output", "Print total", 260, 310), Node("n5", "end", "End", 260, 400)]
    edges = [Edge(nodes[i].id, nodes[i + 1].id) for i in range(len(nodes) - 1)]
    from .models import Flowchart

    fc = Flowchart(name=name, nodes=nodes, edges=edges, stdin="5\n")
    out = Path(args.out) if args.out else Path(f"{name}.flow.json")
    save_flowchart(fc, out)
    print(f"wrote {out} - a 5-block chart you can extend; block types are {', '.join(NODE_TYPES)}")
    return 0


def cmd_gui(args) -> int:
    from .ui.app import main as gui_main

    return gui_main(args.chart)


def cmd_web(args) -> int:
    """Start the editor: a Flask server around the same engine this CLI uses."""
    from .server import app

    host = args.host or "127.0.0.1"
    print(_head("Flow2Code web editor"))
    print(f" open  http://{'127.0.0.1' if host == '0.0.0.0' else host}:{args.port}")
    print(" ctrl+c stops the server")
    if args.reloader:
        app.run(host=host, port=args.port, debug=True, use_reloader=True)
    else:
        from werkzeug.serving import run_simple
        run_simple(host, args.port, app, threaded=True, use_reloader=False)
    return 0


def cmd_samples(args) -> int:
    print(_head("samples"))
    for p in sorted(SAMPLES.glob("*.flow.json")):
        fc = load_flowchart(p)
        bad = all_problems(fc)
        tag = "clean" if not bad else f"{len(bad)} problem(s)"
        note = f" - {fc.note}" if getattr(fc, "note", "") else ""
        print(f" {p.stem:<22} {tag:<12} {len(fc.nodes)} blocks{note}")
    print("\n demo one of them:  python -m flow2code demo even_odd")
    return 0


def cmd_bench(args) -> int:
    """Measure photo mode against its own renders: the numbers the report quotes."""
    from .draw import draw
    from .vision import detect_chart as detect

    print(_head("photo mode, round-trip on the five valid samples"))
    print(" draw each chart, detect it back, compare\n")
    rows, exact, ar_ok, ar_all, blk_ok, blk_all = [], 0, 0, 0, 0, 0
    for name in ("even_odd", "largest_of_two", "sum_loop", "calculator", "nested_if"):
        fc = load_flowchart(SAMPLES / f"{name}.flow.json")
        png = draw(fc, ROOT / f".bench_{name}.png", title=name)
        got, _notes = detect(png)
        key = lambda n: (n.y, n.x)                                     # noqa: E731
        o, g = sorted(fc.nodes, key=key), sorted(got.nodes, key=key)
        m = {gi.id: oi.id for oi, gi in zip(o, g)}
        we = {(e.src, e.dst, e.label) for e in fc.edges}
        ge = {(m[e.src], m[e.dst], e.label) for e in got.edges if e.src in m and e.dst in m}
        ar_ok += len(ge & we)
        ar_all += len(we)
        blk_ok += (len(g) == len(o))
        blk_all += 1
        exact += 1 if (ge == we and len(g) == len(o)) else 0
        rows.append((name, f"{len(g)}/{len(o)}", f"{len(ge & we)}/{len(we)}",
                     "identical" if ge == we and len(g) == len(o) else
                     f"{len(we - ge)} missing, {len(ge - we)} extra"))
        png.unlink(missing_ok=True)
    print(f" {'chart':<18}{'blocks':<9}{'arrows':<9}result")
    print(f" {'-' * 17:<17} {'-' * 8:<9} {'-' * 8:<9} {'-' * 22}")
    for r in rows:
        print(f" {r[0]:<18}{r[1]:<10}{r[2]:<10}{r[3]}")
    print(f"\n {blk_all}/{blk_all} charts recovered every block; {ar_ok}/{ar_all} arrows correct, "
          f"{exact}/{len(rows)} charts came back identical")
    return 0


# --------------------------------------------------------------------------- wiring

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="flow2code", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_text):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(fn=fn)
        return p

    p = add("demo", cmd_demo, "show one sample end to end")
    p.add_argument("name", nargs="?", default="even_odd")
    p.add_argument("--args", nargs="*", help="input lines to feed the program")

    p = add("gen", cmd_gen, "generate Python from a chart")
    p.add_argument("chart")
    p.add_argument("--out")
    p.add_argument("--annotate", action="store_true", help="mark each line with its block id")

    p = add("run", cmd_run, "generate and run it")
    p.add_argument("chart")
    p.add_argument("--args", nargs="*", help="input lines (one per Read block)")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--show", action="store_true", help="print the generated code first")

    p = add("check", cmd_check, "validate a chart and list every problem")
    p.add_argument("chart")

    p = add("render", cmd_render, "draw a chart as a PNG")
    p.add_argument("chart")
    p.add_argument("--png")

    p = add("image", cmd_image, "read a photo or scan of a hand-drawn chart")
    p.add_argument("photo")
    p.add_argument("--out")
    p.add_argument("--name")

    p = add("new", cmd_new, "start a chart from a 5-block skeleton")
    p.add_argument("name", nargs="?", default="my_flow")
    p.add_argument("--out")

    p = add("gui", cmd_gui, "open the editor window")
    p.add_argument("chart", nargs="?", default="")

    w = add("web", cmd_web, "run the editor website (draw, generate, run)")
    w.add_argument("--port", type=int, default=8000)
    w.add_argument("--host", default="", help="0.0.0.0 to show it to the lab")
    w.add_argument("--reloader", action="store_true", help="reload templates while developing")

    add("samples", cmd_samples, "list the sample charts")
    add("bench", cmd_bench, "measure photo mode against its own renders")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except Flow2CodeError as exc:
        print(f"\n{BAR}\n the chart was refused\n{BAR}", file=sys.stderr)
        for line in textwrap.wrap(str(exc), 68) or [str(exc)]:
            print(f" {line}", file=sys.stderr)
        print("\n fix the drawing (or open it in the editor: python -m flow2code gui FILE)",
              file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"no such file: {exc.filename}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

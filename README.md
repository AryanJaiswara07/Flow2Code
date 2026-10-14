# Flow2Code — draw a flowchart in the browser, get a working Python program

A web app with a real backend. You draw a flowchart on a canvas (or upload a photo of one you
drew on paper), the server checks that the chart makes sense, translates every block into Python,
and runs it in a subprocess — printing the program's output back into the same window.

```
  the browser                                    the server (Flask)                the engine
  -------------------------------------          ------------------------          ----------------
  palette: 13 standard shapes                      /api/meta        → shapes      models.py   the type table
  drag, resize, connect, label Yes/No              /api/check       → problems    graph.py    networkx rules
  double-click a block and type into it            /api/generate    → Python      statement.py one block, one line
  Save / Open a .flow.json                         /api/run         → output      codegen/    while, if/elif, indent
  upload a photo of a chart  ---------------------->/api/import/image→ editable   vision.py     OpenCV shapes + arrows
  a picture of the chart                           /api/render       → PNG        draw.py       Pillow
  the code pane shows line numbers + block ids     /api/tidy         → straight   layout.py
                                                   /api/save         → .flow.json  runner.py     subprocess + timeout
```

## Five minutes to run it

Open a terminal **in the folder you extracted** — the one where `requirements.txt` and `README.md`
sit next to `flow2code/`, `samples/` and `tests/`. On Windows that is the folder you unzipped into:
`dir` (Windows) or `ls` should show `requirements.txt`. Do **not** `cd flow2code` — that is the
Python package, not the project.

```bash
pip install -r requirements.txt          # Windows, if pip is not on PATH: py -m pip install -r requirements.txt
python -m flow2code web                  # Windows: py -m flow2code web
```

Then open **http://127.0.0.1:8000**. To show it to a whole lab, use
`python -m flow2code web --host 0.0.0.0 --port 8000` and give them your machine's address.

What to do first, in that order:

1. the app opens with the `even_odd` chart loaded, its Python already generated, and the checker's
   "nothing to complain about" in the Problems tab;
2. **drag a block** from the palette onto the canvas — the code pane immediately says the chart is
   broken and names the orphan block; press <kbd>Ctrl</kbd>+<kbd>Z</kbd> and it is fine again;
3. **click a block, then pull an arrow** out of one of its blue port dots onto another block;
4. **double-click** a block and type `total = a * b` — the Python line changes as you press Enter;
5. type `7` into the **Run** tab's input box and press <kbd>Ctrl</kbd>+<kbd>Enter</kbd>: `Odd`.
6. **Examples** lists the eight files in `samples/`; the three broken ones are marked, and opening
   one shows the checker refusing to generate rather than guessing.
7. **Upload a flowchart photo** (or drag a PNG/JPG onto the canvas): a hand-drawn chart comes back
   as blocks and arrows you can move, and the notes say what could not be read.

`python -m flow2code web --help` shows the port/host/reloader flags. The dev server is single-user
and unguarded — fine for a lab demo, not for the internet.

## The shapes the editor offers

Every one is a standard flowchart symbol, drawn the same way on the canvas, in the PNG the server
renders, and in the palette preview. The last column is what a block of that shape contributes.

| shape | symbol | arrows out | Python |
|---|---|---|---|
| Start / End | stadium | 1 / 0 | nothing but a name |
| Data in | parallelogram | 1 | `n = int(input("Enter n: "))` |
| Data out | parallelogram | 1 | `print(...)` |
| Process | rectangle | 1 | the assignment or call, after `ast.parse` |
| Decision | diamond | **2** | `if …:` / `while …:`, closed at the join |
| Preparation | hexagon | 1 | one statement (initialisation) |
| Document | rectangle with a wavy foot | 1 | one statement |
| Database | cylinder | 1 | one statement |
| Manual input | trapezoid | 1 | one statement |
| Delay | rectangle with a dome | 1 | one statement |
| Connector | small circle | 1 | nothing — it only routes |
| Off-page connector | pentagon | 1 | nothing — it only routes |

Notes (the sticky square in the palette) are drawings, not blocks: they never join the graph and
never reach the code.

## The chart file (`.flow.json`)

One format, used by the website, the command line, photo mode and the tests alike. Save and Open in
the browser read and write exactly this file.

```json
{
  "name": "even_odd",
  "stdin": "7\n",
  "nodes": [
    {"id": "n1", "type": "start",    "text": "Start",         "x": 260, "y":  40},
    {"id": "n2", "type": "input",    "text": "Read n",        "x": 260, "y": 130},
    {"id": "n3", "type": "decision", "text": "n % 2 == 0?",   "x": 260, "y": 235},
    {"id": "n4", "type": "output",   "text": "Print \"Even\"", "x": 120, "y": 345},
    {"id": "n5", "type": "output",   "text": "Print \"Odd\"",  "x": 400, "y": 345},
    {"id": "n6", "type": "end",      "text": "End",           "x": 260, "y": 440}
  ],
  "edges": [
    {"from": "n1", "to": "n2"},
    {"from": "n2", "to": "n3"},
    {"from": "n3", "to": "n4", "label": "yes"},
    {"from": "n3", "to": "n5", "label": "no"},
    {"from": "n4", "to": "n6"},
    {"from": "n5", "to": "n6"}
  ],
  "notes": [{"text": "the diamond is the whole point", "x": 480, "y": 200}]
}
```

`x`, `y` and the optional `w`, `h` are for drawing only; the meaning is entirely in the types and the
arrows. Only a decision may carry labelled arrows, and it must have exactly two.

## What a block's words have to look like

The tool copies, it never guesses: anything outside the right-hand column is refused, with the
block's id in the message, and the problem is highlighted on the canvas.

| block | you write | it becomes |
|---|---|---|
| input | `Read n` | `n = int(input("Enter n: "))` |
| input | `Read a, b` | two `int(input(...))` lines |
| input | `Read x: float` | `x = float(input("Enter x: "))` |
| output | `Print "Even"` | `print("Even")` |
| output | `Display n, total` | `print(n, total)` |
| any statement block | `total = total + i` | copied as written (after `ast.parse`) |
| any statement block | `Set r = a - b` | `r = a - b` |
| decision | `n % 2 == 0?` | `n % 2 == 0` |
| decision | `a = b` | repaired to `a == b`, and told to you |

A statement block may not contain `import`, `eval`, `exec`, `open`, `__` or a second statement. The
generated program runs in a **subprocess** with a 5 second timeout, never with `eval`, and the
browser only ever sees text.

## The rules the checker enforces

1. unique block ids, every arrow points at a block that exists;
2. exactly one Start, at least one End;
3. out-degree follows the type (the table above);
4. only a decision may have labelled arrows, and its two must be Yes and No;
5. no arrow into itself, no duplicated arrow;
6. every block reachable from Start; every block reaches an End.

Then, while generating, two harder things are checked:

7. a decision whose branch comes back to it is a **`while`** loop;
8. otherwise the two branches must meet again at exactly one block, which closes the
   **`if/else`**. If they never meet, or if a block would be printed twice, generation stops and
   names the block. (That meeting point is a post-dominator approximation, which is enough for the
   loop-free and single-loop charts a course draws — see *limits*.)

## The command line, which is still there

Everything the site does, the CLI does too — that is the point of keeping the engine separate.

```bash
python -m flow2code samples            # what is in the box
python -m flow2code demo even_odd      # chart → code → output, one screen
python -m flow2code demo sum_loop
python -m flow2code run samples/calculator.flow.json --args 8 2 -
python -m flow2code gen samples/even_odd.flow.json --annotate     # which block made which line
python -m flow2code check samples/bad_unreachable.flow.json       # the validator, talking plainly
python -m flow2code render samples/nested_if.flow.json --png nested.png
python -m flow2code image photo.png --out chart.flow.json        # picture → editable chart
python -m flow2code bench              # what photo mode actually achieves
python -m flow2code gui samples/even_odd.flow.json               # the Tkinter window, if you prefer
```

## Layout of the code

```
flow2code/
  models.py           Node, Edge, Note, Flowchart, and NODE_KINDS: the one table of 13 shapes
  graph.py            build the networkx graph; problems(); validate(); join detection
  statement.py        one block's words → one or two Python statements
  codegen/
    ast_builder.py    graph → block tree (Raw / Seq / If / While), finding where each closes
    emitter.py        block tree → indented text (and `else { if }` → `elif`)
  loader.py           .flow.json in and out
  runner.py           run it in a subprocess with stdin and a timeout
  draw.py             a chart → a PNG (Pillow), obstacle-aware connectors
  layout.py           auto_layout: rows by depth, what the Tidy button calls
  vision.py           a picture → a chart (OpenCV shapes + a connector hypothesis test)
  server.py           the Flask app: nine JSON routes, no logic of its own
  cli.py              the commands above, including `web`
  web/
    index.html        the single page: header, palette, canvas, output panel
    styles.css        the whole look (no framework, no build step)
    editor.js         ChartEditor: the SVG canvas, all the pointer maths, undo
    app.js            the wiring: palette, tabs, the five API calls, drag-and-drop upload
  ui/
    model.py          every editor rule for the Tkinter window, with no window in sight
    app.py            that window, for anyone who would rather not use a browser
samples/              five valid charts, three deliberately broken ones, and their PNGs
tests/                165 Python tests, and two browser tests under tests/web
```

## What is tested, and how much passes

```bash
python -m pytest -q                # 165 passed   (no screen, no camera, no network)
```

- every sample chart generates, parses with `ast`, and **runs** to the exact expected output
  (`sum_loop` with 100 prints `sum is 5050`);
- each of the eight rules has a test that triggers it and reads the message;
- all 13 shapes: they draw, they report an outline, they translate (or deliberately do not), and
  they round-trip through a file;
- the HTTP layer: the page and its scripts are served, `/api/generate` traces every line back to
  its block, a broken chart is refused with the block id attached, `/api/run` executes in a
  subprocess, an infinite loop is cut off, junk JSON gets a polite error instead of a traceback,
  and the upload route reads a drawn chart back;
- **the browser side**, with jsdom and no browser: `cd tests/web && npm install jsdom`, run the app
  (`python -m flow2code web --port 8000 &`) and then
  `F2C=http://127.0.0.1:8000 node smoke.mjs && node interact.mjs` — 33 checks on the wiring
  (palette, panes, undo, tidy, run, examples, the draft in localStorage) and 23 on the pointer
  (drag, snap, connect through a port handle, resize with a minimum, typing into a shape,
  auto-labelling a decision, deleting an arrow). 56 in all, and they need no browser.

Photo mode's measured result (`python -m flow2code bench`), on the five valid samples:

| chart | blocks | arrows | result |
|---|---|---|---|
| even_odd | 6/6 | 6/6 | identical |
| largest_of_two | 7/7 | 7/7 | identical |
| sum_loop | 9/9 | 8/9 | one arrow missing, none invented |
| calculator | 10/10 | 11/11 | identical |
| nested_if | 8/8 | 9/9 | identical |

41 of 42 arrows recovered, 4 of 5 charts returned unchanged, no false arrows anywhere.

## Known limits (say these before someone finds them)

- **The web app is a demo server.** No login, no database, one chart at a time, and the draft lives
  in the browser's localStorage. `Save` writes the file on *your* machine; the "into samples/"
  button writes on the machine running the server.
- **The editor is hand-written vanilla JS** (no draw.io, no React): it does the things a flowchart
  needs and nothing else — no multi-select, no copy/paste, no rotating, no dashed lines, one arrow
  label at a time.
- **Connectors are routing only.** Two circles named `A` are not yet joined into one path, so a
  chart that uses an off-page connector to skip a page still has to be drawn end to end.
- **`sum_loop`'s loop-back arrow** runs beside the loop body into the same block, so its ink touches
  the branch arrow and the two become one stroke; the detector reports the chart as unfinished
  instead of guessing. That is why the sample set has broken charts in it: the tool's job is to
  notice.
- **Text from a photo needs Tesseract.** Without `pytesseract` plus the `tesseract` program (see
  `requirements.txt`), shapes, arrows and Yes/No sides still come back — they are geometry — but the
  words do not, so an upload arrives with empty blocks and a note saying so. Type into them and the
  code appears.
- **Join detection is a post-dominator approximation**: charts where two branches of *different*
  decisions cross each other are refused, not attempted. No `for` loop is generated yet (a
  counter-test-increment diamond becomes `while`), and a block still holds one statement.
- `draw.py` and `vision.py` are tuned for the shapes this tool draws. A busy whiteboard photo with
  handwriting and shadows needs more thresholds than a prototype should pretend to have.

## Next, if it grew

`for` loops and repeat-until, prompts taken from the block's text, matched off-page connectors, a
real post-dominator (Lengauer-Tarjan) so crossing branches are allowed, multi-line blocks, saving
charts on the server (a folder or SQLite, with a login), and `pyproject.toml` so it installs as
`flow2code`.

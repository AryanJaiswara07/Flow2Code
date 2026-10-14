# The five-minute demonstration

The website is the demonstration. Start it, then talk while you click.

```bash
pip install -r requirements.txt
python -m flow2code web                 # Windows: py -m flow2code web
# open http://127.0.0.1:8000
```

Nothing here needs a camera or the internet. If the projector or the browser is a problem, the
fallback at the bottom is the same engine from the command line.

### 1. What is on the screen (30 s)

The app opens with the `even_odd` chart already drawn, its Python on the right, and the Problems tab
saying the checker found nothing.

Say: six blocks and six arrows on the left; eight lines on the right. Nobody typed the Python — every
line has the id of the block it came from in the gutter, and clicking one of those ids selects the
block on the canvas.

### 2. Draw something, and break it on purpose (60 s)

Drag a **Process** rectangle out of the palette and drop it in the corner.

The code pane goes away and says *"the chart has 2 problems, so nothing was generated"*. The Problems
tab names the block — `p1` cannot be reached from Start, and has no path to an End — and the block is
outlined in red on the canvas. Click the `p1` chip in the problem to jump to it.

Press <kbd>Ctrl</kbd>+<kbd>Z</kbd>: the block goes away, the code comes back. Say: the checker is not
a warning, it is the reason there is no guessing in the output.

### 3. The two things that make it a program (90 s)

Open **Examples → largest of two**. Then:

- click the diamond, pull an arrow from a blue port dot onto a block, and the two arrows of a
  decision are labelled `yes` / `no` for you;
- double-click any block, type `total = a * b`, press Enter — the Python line changes as you release
  the key;
- **Tidy** straightens a messy chart into rows (that is `layout.py`, one row per level of depth);
- **Picture** shows the PNG the server drew, which is the file you can put in the report.

Then type `7` in the **Run** tab's input box and press <kbd>Ctrl</kbd>+<kbd>Enter</kbd>: it prints
`Odd`, exit 0 in a few tens of milliseconds. Say: that ran in a separate Python process with a
5-second limit, so a loop that never ends gets cut off instead of hanging the machine.

### 4. A loop, because that is the hard part (45 s)

**Examples → sum of 1..n**. Point at the diamond `i <= n?`: one arrow leaves it and one comes back.
That is the shape of a `while` loop, and this is what makes it one — the generator walks the chart and
the arrow returning to a block it is already inside *becomes* the loop.

Run it with `100`: `sum is 5050`.

### 5. It refuses the drawings that would lie (45 s)

**Examples** lists three charts marked *broken on purpose*:

| chart | what is wrong | who catches it |
|---|---|---|
| missing branch | a diamond with only one way out | rule 4, the graph |
| unreachable | a block nobody can reach from Start | rule 6, the graph |
| crossing | two branches that never join up | rule 8, while generating |

The third is the interesting one: the chart is legal as a picture, and only the generator can say
"this block would be printed twice". It names the block and generates nothing.

### 6. A photo of a hand-drawn chart (60 s)

Print or open `samples/calculator.png`, then **Upload a flowchart photo** (or drag the file onto the
canvas). The blocks and arrows come back as an editable chart: 10 blocks, 11 arrows. Move one, and
the Python follows.

Then run `python -m flow2code bench` in a terminal and show the numbers: **41 of 42 arrows** on the
five samples, no invented arrows, and the one missing arrow *reported* rather than guessed. Say out
loud what the notes in the Problems tab say: without Tesseract installed the words inside the shapes
do not come back, so the chart arrives empty of text — that is the honest limit of this part.

### Questions you should expect

- **"Why not just use draw.io and a plugin?"** Because the point is the translation: a graph that is
  checked against eight rules and turned into an AST-checked program. The editor is 829 lines of hand-written
  SVG plus 617 lines of wiring, so every interaction can be explained.
- **"Why not use an AST library to build the program?"** The structure is what is being taught; `ast`
  is used to *check* — every block's text is parsed before it is kept, and the finished program is
  parsed again, so a broken program can never be handed to the runner.
- **"How do you know a branch closes here and not later?"** The two branches must meet again at exactly
  one block; that block is where the `if/else` closes. If they never meet, the tool stops rather than
  indenting a guess.
- **"Is it safe to run generated code?"** It runs in a `subprocess` with a timeout and no inherited
  environment; and a block containing `import`, `eval`, `exec` or `open` is refused before anything is
  emitted.
- **"Where are the tests?"** `python -m pytest -q` — 165 of them, no screen or camera needed — plus
  55 jsdom checks that drive the real page (`tests/web`).

### The fallback, if the browser will not cooperate

```bash
python -m flow2code demo even_odd            # chart → code → output, one screen
python -m flow2code demo sum_loop
python -m flow2code run samples/calculator.flow.json --args 8 2 -
python -m flow2code check samples/bad_unreachable.flow.json
python -m flow2code bench
```

Same engine, no HTTP: the website contains no logic the command line cannot reach.

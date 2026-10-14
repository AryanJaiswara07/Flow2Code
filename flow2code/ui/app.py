"""A small editor window: draw the flowchart, watch the Python appear next to it.

This is the part of the project a viva audience should touch, and it is deliberately thin: every
decision (what may connect to what, what is wrong with the chart, what code it means) lives in
:class:`flow2code.ui.model.EditorState`, which is tested without a screen.  What is left here is
drawing and mouse events, which is why a headless machine can still prove the tool works.
"""
from __future__ import annotations

import sys
from typing import Optional

from ..graph import Flow2CodeError
from ..layout import auto_layout
from ..loader import load_flowchart, save_flowchart
from .model import EditorState
from ..runner import run

INK = "#111111"
PAPER = "#ffffff"
FILL = "#fafafa"
SEL = "#c8c8c8"

TYPES = ("start", "input", "process", "decision", "output", "end")
W, H = 620, 520


class EditorApp:
    """The window itself."""

    def __init__(self, tk_root, state: Optional[EditorState] = None):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.state = state or EditorState()
        self.root = tk_root
        tk_root.title("Flow2Code - draw the chart, get the program")
        tk_root.geometry(f"{W + 340}x{H + 120}")
        tk_root.configure(bg=PAPER)

        bar = ttk.Frame(tk_root)
        bar.pack(side="top", fill="x", padx=6, pady=4)
        for label in ("New", "Open", "Save", "Check", "Run", "Tidy", "Undo"):
            ttk.Button(bar, text=label, command=lambda l=label: self.action(l)).pack(
                side="left", padx=2)
        ttk.Label(bar, text="  block:").pack(side="left")
        self.palette = tk.StringVar(value="process")
        for t in TYPES:
            ttk.Radiobutton(bar, text=t, value=t, variable=self.palette).pack(side="left")

        left = ttk.Frame(tk_root)
        left.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(left, width=W, height=H, bg=PAPER, highlightthickness=1,
                                highlightbackground=INK)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)

        right = ttk.LabelFrame(tk_root, text=" python, generated from the chart as you draw")
        right.pack(side="left", fill="y", padx=6, pady=6)
        self.code = tk.Text(right, width=44, height=30, bg=PAPER, fg=INK, font=("DejaVu Sans Mono", 10),
                            relief="flat")
        self.code.pack(fill="both", expand=True, padx=4, pady=4)
        self.err = tk.Text(right, width=44, height=8, bg="#f4f4f4", fg="#8a1c1c",
                           font=("DejaVu Sans Mono", 9), relief="flat")
        self.err.pack(fill="x", padx=4, pady=(0, 4))

        self.status = ttk.Label(tk_root, text=self.state.message or "click the canvas to place "
                                "the selected block; drag between blocks to connect them; "
                                "double-click a block to edit its words; right-click an arrow "
                                "to switch Yes/No", background=PAPER, foreground=INK)
        self.status.pack(side="bottom", fill="x", padx=8)

        self.selected: Optional[str] = None
        self.drag_from: Optional[str] = None
        self.ghost = None
        c = self.canvas
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-ButtonPress-1>", self.on_double)
        c.bind("<ButtonPress-3>", self.on_right)
        c.bind("<Delete>", lambda e: self.delete_selected())
        c.bind("<Configure>", lambda e: self.redraw())

        self.redraw()

    # ------------------------------------------------------------------ events
    def on_press(self, event):
        nid = self.state.hit_test(event.x, event.y)
        self.selected = nid
        if nid is None:
            self.add_at(event.x, event.y)
        else:
            self.drag_from = nid
            self.start_x, self.start_y = event.x, event.y
        self.redraw()

    def add_at(self, x, y):
        try:
            self.state.add_block(self.palette.get(), x, y)
        except Flow2CodeError as exc:
            self.say(str(exc))

    def on_drag(self, event):
        if self.drag_from is None:
            return
        self.canvas.delete("ghost")
        nid = self.state.hit_test(event.x, event.y)
        if nid and nid != self.drag_from:
            x0, y0 = self.center(self.drag_from)
            self.canvas.create_line(x0, y0, event.x, event.y, dash=(4, 3), tags="ghost")
        elif not nid:
            x0, y0 = self.center(self.drag_from)
            self.canvas.create_line(x0, y0, event.x, event.y, dash=(4, 3), tags="ghost")

    def on_release(self, event):
        if self.drag_from is None:
            return
        target = self.state.hit_test(event.x, event.y)
        src = self.drag_from
        self.drag_from = None
        self.canvas.delete("ghost")
        if target and target != src:
            try:
                self.state.connect(src, target)
            except Flow2CodeError as exc:
                self.say(str(exc))
        elif target is None and (abs(event.x - self.start_x) > 6 or abs(event.y - self.start_y) > 6):
            self.state.move_block(src, event.x, event.y)      # it was a drag, not a connection
        self.redraw()

    def on_double(self, event):
        nid = self.state.hit_test(event.x, event.y)
        if not nid:
            return
        from tkinter import simpledialog

        node = self.state.fc.by_id()[nid]
        text = simpledialog.askstring("Block text", f"{nid} is a {node.type} block.\n"
                                      f"Write what happens in it:", initialvalue=node.text,
                                      parent=self.root)
        if text is not None:
            self.state.set_text(nid, text.strip())
        self.redraw()

    def on_right(self, event):
        hit = self.state.edge_hit(event.x, event.y)
        if hit:
            self.state.toggle_label(*hit)
            self.redraw()
            return
        nid = self.state.hit_test(event.x, event.y)
        if nid:
            from tkinter import simpledialog

            node = self.state.fc.by_id()[nid]
            kind = simpledialog.askstring("Block type", f"{nid}: one of {', '.join(TYPES)}",
                                          initialvalue=node.type, parent=self.root)
            if kind:
                try:
                    self.state.set_type(nid, kind.strip())
                except Flow2CodeError as exc:
                    self.say(str(exc))
                self.redraw()

    def delete_selected(self):
        if self.selected:
            self.state.delete_block(self.selected)
            self.selected = None
            self.redraw()

    # ------------------------------------------------------------------ buttons
    def action(self, name):
        if name == "New":
            self.state = EditorState()
            self.selected = None
        elif name == "Open":
            from tkinter import filedialog

            path = filedialog.askopenfilename(filetypes=[("flowchart", "*.flow.json"),
                                                          ("all", "*.*")])
            if path:
                self.state = EditorState(load_flowchart(path))
        elif name == "Save":
            from tkinter import filedialog

            path = filedialog.asksaveasfilename(defaultextension=".flow.json",
                                                filetypes=[("flowchart", "*.flow.json")])
            if path:
                save_flowchart(self.state.fc, path)
                self.say(f"saved {path}")
        elif name == "Tidy":
            self.state.push_undo()
            auto_layout(self.state.fc)
        elif name == "Undo":
            self.state.undo()
        elif name == "Check":
            self.check()
        elif name == "Run":
            self.run_it()
        self.redraw()

    def check(self):
        bad = self.state.check()
        self.show_errors("\n".join(f"- {b}" for b in bad) if bad else "no problems: the chart "
                         "is a program waiting to happen")
        return not bad

    def run_it(self):
        if not self.check():
            return
        code = self.state.code()
        from tkinter import simpledialog

        stdin = simpledialog.askstring("Input", "One line per Read block (blank if none):",
                                       parent=self.root) or ""
        res = run(code, stdin="\n".join(stdin.split()) + "\n" if stdin.strip() else "")
        self.show_errors((res.stdout + ("\n" + res.describe() if not res.ok else "")).strip())
        self.say("ran: " + ("ok" if res.ok else "it failed, output above"))

    # ------------------------------------------------------------------ drawing
    def center(self, nid):
        n = self.state.fc.by_id()[nid]
        return n.x, n.y

    def say(self, msg):
        self.state.message = msg
        try:
            self.status.configure(text=msg)
        except Exception:                              # pragma: no cover - window closing
            pass

    def show_errors(self, text):
        self.err.delete("1.0", "end")
        self.err.insert("1.0", text)

    def redraw(self):
        c = self.canvas
        c.delete("all")
        c.create_text(12, 12, anchor="w", text=self.state.fc.name, fill=INK,
                      font=("DejaVu Sans", 12, "bold"))
        for e in self.state.fc.edges:
            try:
                ax, ay = self.center(e.src)
                bx, by = self.center(e.dst)
            except KeyError:
                continue
            c.create_line(ax, ay, bx, by, fill=INK, width=2, arrow="last")
            if e.label:
                c.create_text((ax + bx) / 2, (ay + by) / 2 - 8, text=e.label, fill="#666666",
                              font=("DejaVu Sans", 9))
        from ..draw import _text_lines, outline_points            # reuse the real shapes
        for n in self.state.fc.nodes:
            pts = [p for p in outline_points(n)]
            if n.type in ("start", "end"):
                x0, y0, x1, y1 = _bounds(n)
                c.create_oval(x0, y0, x1, y1, fill=FILL, outline=INK, width=2)
            else:
                c.create_polygon(pts, fill=SEL if n.id == self.selected else FILL, outline=INK,
                                 width=2, smooth=False)
            lines = _text_lines(n, self.font())
            for i, line in enumerate(lines):
                c.create_text(n.x, n.y + (i - (len(lines) - 1) / 2) * 15, text=line, fill=INK,
                              font=("DejaVu Sans", 10))
        self.refresh_code()

    def font(self):
        from ..draw import _font

        return _font(11)

    def refresh_code(self):
        try:
            code = self.state.code(annotate=True)
            self.show_errors("")
        except Flow2CodeError as exc:
            code = ""
            self.show_errors(str(exc))
        self.code.delete("1.0", "end")
        self.code.insert("1.0", code or "# not a program yet - fix the red text below")


def _bounds(n):
    from ..draw import bounds_of

    return bounds_of(n)


def main(path: str = "") -> int:
    """Open the editor.  Returns an exit code so the CLI can stay honest about failures."""
    try:
        import tkinter as tk
    except Exception as exc:                                # pragma: no cover
        print(f"no tkinter on this python ({exc})", file=sys.stderr)
        return 2
    state = None
    if path:
        try:
            state = EditorState(load_flowchart(path))
        except Flow2CodeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    try:
        root = tk.Tk()
    except Exception as exc:                                # pragma: no cover
        print(f"cannot open a window here ({exc}); the model and the CLI still work: "
              f"python -m flow2code demo even_odd", file=sys.stderr)
        return 2
    EditorApp(root, state)
    root.mainloop()
    return 0

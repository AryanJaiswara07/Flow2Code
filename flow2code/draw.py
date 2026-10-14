"""Draw a chart to a PNG with Pillow.

Two reasons this lives next to the generator instead of inside a GUI: the photo mode needs
it (it renders a chart, then detects it back, which is how that half of the project is
testable without a camera), and a screenshot of a sample is the cheapest possible slide.

Shapes follow the standard flowchart symbols, because the shape *is* the type: a diamond is
a decision whether or not anyone reads the words inside it.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .models import Flowchart, Node

Color = Tuple[int, int, int]

INK: Color = (25, 25, 25)
PAPER: Color = (255, 255, 255)
FILL: Color = (250, 250, 250)
ACCENT: Color = (120, 120, 120)

PAD = 46             # margin around the drawing, in px


def _font(size: int = 17):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text_lines(node: Node, font) -> List[str]:
    raw = (node.text or "").strip() or node.type
    words, lines, width = raw.split(), [], 0
    limit = node.size()[0] - 26          # wrap inside the shape, with a little air
    for w in words:
        trial = (lines[-1] + " " + w).strip() if lines else w
        if font.getlength(trial) <= limit or not lines:
            if lines:
                lines[-1] = trial
            else:
                lines = [trial]
        else:
            lines.append(w)
        width = max(width, font.getlength(lines[-1]))
    return lines[:3]


class _Painter:
    """Small wrapper so the drawing code reads like geometry, not like Pillow."""

    def __init__(self, size: Sequence[int]):
        from PIL import Image, ImageDraw

        self.img = Image.new("RGB", (int(size[0]), int(size[1])), PAPER)
        self.d = ImageDraw.Draw(self.img)
        self.font = _font()

    def shape(self, pts: Sequence[Tuple[float, float]], outline=INK, width=2):
        # polygon(outline=...) leaves a pixel or two open where two edges meet at a sharp
        # corner, which is enough for a diamond to "leak" into the background; a closed
        # joint="curve" polyline does not
        pts = [tuple(p) for p in pts]
        self.d.polygon(pts, fill=FILL)
        self.d.line(pts + [pts[0]], fill=outline, width=width, joint="curve")

    def line(self, a, b, fill=INK, width=2):
        self.d.line([tuple(a), tuple(b)], fill=fill, width=width)

    def text(self, cx, cy, lines: Sequence[str], fill=INK):
        h = len(lines) * 21
        y = cy - h / 2 + 3
        for ln in lines:
            w = self.font.getlength(ln)
            self.d.text((cx - w / 2, y), ln, fill=fill, font=self.font)
            y += 21

    def arrow_head(self, tip, angle, fill=INK):
        import math

        size = 11
        pts = [(tip[0] - size * math.cos(angle - 0.4), tip[1] - size * math.sin(angle - 0.4)),
               (tip[0] - size * math.cos(angle + 0.4), tip[1] - size * math.sin(angle + 0.4)),
               tip]
        self.d.polygon([tuple(p) for p in pts], fill=fill)

    def save(self, path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.img.save(p)
        return p


def bounds_of(node: Node) -> Tuple[float, float, float, float]:
    """The box a shape is drawn inside, from its own w/h or the default for its symbol."""
    w, h = node.size()
    return node.x - w / 2.0, node.y - h / 2.0, node.x + w / 2.0, node.y + h / 2.0


def outline_points(node: Node) -> List[Tuple[float, float]]:
    """The closed polygon of each standard symbol, as a plain point list.

    Everything here is deliberately polygonal: it is what the click test in the editor, the
    arrow anchors here, and the convexity test in vision.py all agree on.  Two shapes (the
    terminal stadium and the database rim) also get an extra curve drawn on top.
    """
    x0, y0, x1, y1 = bounds_of(node)
    cx, cy = node.x, node.y
    w, h = x1 - x0, y1 - y0
    shape = node.shape
    if shape == "diamond":
        return [(cx, y0), (x1, cy), (cx, y1), (x0, cy)]
    if shape == "io":
        s = min(20.0, w * 0.13)
        return [(x0 + s, y0), (x1, y0), (x1 - s, y1), (x0, y1)]
    if shape == "manual":
        s = min(22.0, w * 0.16)
        return [(x0, y0), (x1, y0), (x1 - s, y1), (x0 + s, y1)]
    if shape == "hexagon":
        s = min(26.0, w * 0.18)
        return [(x0 + s, y0), (x1 - s, y0), (x1, cy), (x1 - s, y1), (x0 + s, y1), (x0, cy)]
    if shape == "document":
        amp = min(9.0, h * 0.22)
        pts = [(x0, y0), (x1, y0), (x1, y1 - amp)]
        for i in range(1, 9):                        # the wavy bottom, right to left
            t = i / 8.0
            pts.append((x1 - (x1 - x0) * t, y1 - amp + amp * math.sin(math.pi * (1 - t))))
        pts.append((x0, y1 - amp))
        return pts
    if shape == "database":
        r = min(12.0, h * 0.2)
        return [(x0, y0 + r), (x0, y1 - r), (x1, y1 - r), (x1, y0 + r)]
    if shape == "circle":                              # the on-page connector
        r = min(w, h) / 2.0
        return [(cx + r * math.cos(a), cy + r * math.sin(a))
                for a in [i * math.pi / 8 for i in range(16)]]
    if shape == "pentagon":
        s = min(16.0, h * 0.28)
        return [(x0, y0), (x1, y0), (x1, y1 - s), (cx, y1), (x0, y1 - s)]
    if shape == "delay":
        r = h / 2.0
        pts = [(x0, y0), (x1 - r, y0)]
        for i in range(1, 9):                        # the dome on the right
            a = -math.pi / 2 + math.pi * i / 8.0
            pts.append((x1 - r + r * math.cos(a), cy + r * math.sin(a)))
        pts.append((x1 - r, y1))
        pts.append((x0, y1))
        return pts
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _anchor(node: Node, side: str) -> Tuple[float, float]:
    """Where an arrow touches a shape: the middle of a side, with the leaning shapes pulled in.

    A diamond is drawn to its points and a data parallelogram is narrowest at its own mid-line,
    so an arrow that ends at the box edge would visibly stop short of the ink.
    """
    x0, y0, x1, y1 = bounds_of(node)
    cx, cy = node.x, node.y
    if side in ("left", "right"):
        w = x1 - x0
        lean = {"io": 20.0, "manual": 22.0}.get(node.shape)
        if lean:
            inset = min(lean, w * (0.13 if node.shape == "io" else 0.16)) / 2.0
            return (x0 + inset, cy) if side == "left" else (x1 - inset, cy)
    return {"top": (cx, y0), "bottom": (cx, y1), "left": (x0, cy), "right": (x1, cy)}[side]


def _sides(src: Node, dst: Node, back: bool) -> Tuple[str, str]:
    if back:                                     # dst is above src: a loop back edge, which
        # hugs the near side of the drawing so it never cuts through another column
        return ("left", "left") if src.x <= dst.x else ("right", "right")
    if src.type == "decision":
        return ("left" if dst.x < src.x - 4 else "right" if dst.x > src.x + 4 else "bottom"), "top"
    return "bottom", "top"


def _loop_entry(dst: Node, side: str) -> Tuple[float, float]:
    """Where a loop-back arrow arrives: beside the corner, not on it.

    Two arrows that share a vertex are one blob of ink, and no reader - human or program - can
    tell which is which.  Landing a little down the lower edge keeps them apart.
    """
    x0, y0, x1, y1 = bounds_of(dst)
    if dst.type != "decision":
        return (dst.x, y1) if side == "right" else (dst.x, y1)
    vx = x0 if side == "left" else x1
    t = 0.34                                          # from the side vertex towards the bottom
    return (vx + (dst.x - vx) * t, (dst.y + (y1 - dst.y) * t))


def _boxes(fc: Flowchart, skip) -> List[Tuple[float, float, float, float]]:
    out = []
    for n in fc.nodes:
        if n.id in skip:
            continue
        x0, y0, x1, y1 = bounds_of(n)
        out.append((x0 - 6, y0 - 6, x1 + 6, y1 + 6))
    return out


def _hits(pts, boxes) -> int:
    """How many other blocks this polyline would cut through (0 is the only acceptable answer)."""
    bad = 0
    for (x0, y0, x1, y1) in boxes:
        hit = False
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            steps = max(2, int(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5))
            for i in range(steps + 1):
                x, y = ax + (bx - ax) * i / steps, ay + (by - ay) * i / steps
                if x0 < x < x1 and y0 < y < y1:
                    hit = True
        bad += hit
    return bad


def _candidates(src: Node, dst: Node, boxes, off: float = 0.0
                  ) -> List[Tuple[float, float]]:
    """How to join two blocks, best first.

    A straight diagonal is tried, then the two right-angle routes people actually draw with a
    ruler.  The first one that does not pass through somebody else's box wins; if all of them
    do, the one that passes through the fewest is drawn, because an honest overlap is better
    than a lie.
    """
    a_bot = (src.x, bounds_of(src)[3])
    # ``off`` spreads the entry point of two arrows that share a target: they then arrive at
    # different points of the box instead of stacking on one pixel
    b_top = (dst.x + off, bounds_of(dst)[1])
    mid_y = (a_bot[1] + b_top[1]) / 2
    right = bounds_of(dst)[0] < src.x or dst.x >= src.x
    b_side = (bounds_of(dst)[0], dst.y) if dst.x >= src.x else (bounds_of(dst)[2], dst.y)
    cands: List[List[Tuple[float, float]]] = []
    if src.type == "decision":
        side = "left" if dst.x < src.x - 4 else ("right" if dst.x > src.x + 4 else None)
        if side:
            cands.append([_anchor(src, side), b_top])
    cands.append([a_bot, b_top])                            # straight
    cands.append([a_bot, (dst.x + off, a_bot[1]), b_top])   # across, then down
    cands.append([a_bot, (src.x, dst.y), b_side])           # down, then across into the side
    cands.append([a_bot, (src.x, mid_y), (dst.x + off, mid_y), b_top])
    far = max(bounds_of(n)[2] for n in [src, dst]) + 24
    near = min(bounds_of(n)[0] for n in [src, dst]) - 24
    cands.append([_anchor(src, "right"), (far, a_bot[1]), (far, dst.y),
                  (bounds_of(dst)[2], dst.y)])               # go round the right
    cands.append([_anchor(src, "left"), (near, a_bot[1]), (near, dst.y),
                  (bounds_of(dst)[0], dst.y)])               # go round the left
    del right
    for c in cands:
        if _hits(c, boxes) == 0:
            return c
    return min(cands, key=lambda c: _hits(c, boxes))


def draw(fc: Flowchart, path, title: Optional[str] = None) -> Path:
    """Render ``fc`` and save a PNG.  Returns the path."""
    import math

    nodes = list(fc.nodes)
    if not nodes:
        raise ValueError("nothing to draw: the chart has no blocks")
    xs = [b for n in nodes for b in bounds_of(n)[::2]]
    ys = [b for n in nodes for b in bounds_of(n)[1::2]]
    x0, x1, y0, y1 = min(xs) - PAD, max(xs) + PAD, min(ys) - PAD, max(ys) + PAD
    head = 58 if title else 0
    painter = _Painter((x1 - x0, y1 - y0 + head))
    d = painter.d

    if title:
        tfont = _font(22)
        w = tfont.getlength(title)
        d.text(((x1 - x0) / 2 - w / 2, 16), title, fill=INK, font=tfont)

    def shift(p):
        return (p[0] - x0, p[1] - y0 + head)

    by_id: Dict[str, Node] = {n.id: n for n in nodes}
    labels: List[Tuple[Tuple[float, float], str]] = []
    incoming: Dict[str, List[int]] = {}
    order = []
    for k, e in enumerate(fc.edges):
        incoming.setdefault(e.dst, []).append(id(e))
    place = {k: (i, len(v)) for v in incoming.values() for i, k in enumerate(v)}
    del order
    # connectors first, so the blocks always sit on top of them
    for e in fc.edges:
        src, dst = by_id.get(e.src), by_id.get(e.dst)
        if src is None or dst is None:
            continue
        eid = id(e)
        boxes = _boxes(fc, {src.id, dst.id})
        back = dst.y < src.y - 20
        if back:                                     # a loop: go round the near side, in grey
            s_side, _ = _sides(src, dst, True)
            if s_side == "left":
                off = min(bounds_of(n)[0] for n in nodes) - 22
                ang = 0.0
            else:
                off = max(bounds_of(n)[2] for n in nodes) + 22
                ang = math.pi
            a, b = _anchor(src, s_side), _loop_entry(dst, s_side)
            pts, colour = [a, (off, a[1]), (off, b[1]), b], ACCENT
            lab = (off, (a[1] + b[1]) / 2)
        else:
            i, cnt = place.get(eid, (0, 1))
            off = (i - (cnt - 1) / 2.0) * 28.0
            pts = _candidates(src, dst, boxes, off)
            colour = INK
            ang = math.atan2(pts[-1][1] - pts[-2][1], pts[-1][0] - pts[-2][0])
            lab = (pts[0][0] + (pts[1][0] - pts[0][0]) * 0.45,
                   pts[0][1] + (pts[1][1] - pts[0][1]) * 0.45)
        ip = [shift(p) for p in pts]
        for i in range(1, len(ip)):
            d.line([ip[i - 1], ip[i]], fill=colour, width=2)
        painter.arrow_head(ip[-1], ang, colour)
        if e.label:
            # the word goes beside the line, never on it: a white box behind the label used to
            # cut the connector in two, and the detector then found half an arrow
            (lx, ly), (mx, my) = pts[0], pts[1]
            dx, dy = mx - lx, my - ly
            L = (dx * dx + dy * dy) ** 0.5 or 1.0
            px, py = (-dy / L, dx / L) if dx < 0 else (dy / L, -dx / L)
            labels.append((shift((lab[0] + px * 19, lab[1] + py * 19)), e.label))

    for (lx, ly), txt in labels:                 # last of all, so they read clearly
        w = painter.font.getlength(txt)
        d.text((lx - w / 2, ly - 10), txt, fill=ACCENT, font=painter.font)

    for n in nodes:
        if n.shape == "terminal":                       # the terminator is a stadium
            bx0, by0 = shift((bounds_of(n)[0], bounds_of(n)[1]))
            bx1, by1 = shift((bounds_of(n)[2], bounds_of(n)[3]))
            d.rounded_rectangle([bx0, by0, bx1, by1], radius=(by1 - by0) / 2, fill=FILL,
                                outline=INK, width=2)
        else:
            painter.shape([shift(pt) for pt in outline_points(n)])
            if n.shape == "database":                    # the rim that makes it read as a drum
                bx0, by0 = shift((bounds_of(n)[0], bounds_of(n)[1]))
                bx1, by1 = shift((bounds_of(n)[2], bounds_of(n)[1] + min(24.0,
                                                                         n.size()[1] * 0.4)))
                d.ellipse([bx0, by0, bx1, by1], fill=FILL, outline=INK, width=2)
        painter.text(*shift((n.x, n.y)), _text_lines(n, painter.font))
    return painter.save(path)



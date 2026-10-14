"""Photo mode: a picture of a flowchart in, an editable chart out.

What this file actually does, stated plainly:

* **shapes** come from the enclosed white space inside each block, not from the outlines.
  That is the one design decision that makes the whole thing work: an arrow that touches a box
  merges box and arrow into a single piece of ink, so outlines cannot be separated — but the
  empty paper inside each shape can be.  A diamond, a rectangle, a parallelogram and a stadium
  then differ enough in vertex count and in how much of their bounding box they fill.
* **arrows** are a hypothesis test, not a line detector: for every ordered pair of blocks, ask
  "does ink run from the edge of one to the edge of the other?" along a straight route and, for
  a back edge, along the two side routes.  Direction comes from the arrowhead (a filled wedge is
  locally denser than a bare line end).
* **text** is read only when Tesseract is installed; without it the blocks come back with empty
  text and the structure is still right, because ids and positions carry the graph.
* **Yes/No labels** come from the drawing convention, not from the words: from a decision, the
  branch leaving to the left is Yes and the one to the right is No — which is how
  :mod:`flow2code.draw` draws them and how most people draw them too.

So this module can be tested with no camera: draw a chart, detect it back, compare.
``tests/test_vision.py`` does exactly that for every sample.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .graph import Flow2CodeError
from .models import Edge, Flowchart, Node

MIN_AREA = 1200            # px^2 of paper inside a shape; below that it is a letter
BLOCK_GAP = 40.0           # px of blank a connector may cross: a Yes/No word sits there


@dataclass
class Block:
    """One shape that was found, before it becomes a Node."""
    cx: float
    cy: float
    type: str                                   # terminal | io | process | decision
    text: str = ""
    poly: Tuple[Tuple[float, float], ...] = ()
    area: float = 0.0


# --------------------------------------------------------------------------- shapes

def _binarize(image_path):
    """Grey image plus a thick, tidy ink mask.

    Dark ink on light paper, whether that is a render, a printout or a whiteboard photo; an
    arrow that stops on a sharp corner leaves a one-pixel sliver of paper beside its tip, and
    thickening the ink by a pixel is enough to seal it.
    """
    import cv2

    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise Flow2CodeError(f"could not read an image from {image_path}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    th = cv2.dilate(th, np.ones((3, 3), np.uint8))
    return img, gray, _drop_small_ink(th)


def _drop_small_ink(th):
    """Delete loose specks of ink (letters, digits) before shapes are looked for.

    Without this, a word that happens to touch an outline cuts that block's interior in half
    and the block vanishes.  Words are read later from the grey image, so nothing is lost.
    """
    import cv2

    n, lab, stats, _ = cv2.connectedComponentsWithStats(th, 8)
    out = th.copy()
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 900 and w < 60 and h < 44:
            out[lab == i] = 0
    return out


def _regions(th) -> List[Tuple[float, float, Tuple[int, int, int, int], float, np.ndarray]]:
    """The enclosed white areas: one per block interior, letters' holes thrown away."""
    import cv2

    white = 255 - th
    n, lab, stats, _ = cv2.connectedComponentsWithStats(white, 8)
    h, w = th.shape
    found = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if x <= 0 or y <= 0 or x + bw >= w or y + bh >= h:          # the page itself
            continue
        if not (MIN_AREA <= area <= 4_000_000) or bw < 24 or bh < 18:
            continue
        mask = (lab == i).astype(np.uint8)
        m = cv2.moments(mask)
        if m["m00"] == 0:
            continue
        # every flowchart symbol is convex, and so is the paper inside it; the empty space
        # between four blocks and their arrows is not (measured 0.98+ vs 0.67), so this one
        # number throws away the "hole in the middle of the drawing" false block
        cs, _ = cv2.findContours(mask * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cs:
            continue
        c = max(cs, key=cv2.contourArea)
        hull_area = cv2.contourArea(cv2.convexHull(c))
        if hull_area <= 0 or cv2.contourArea(c) / hull_area < 0.90:
            continue
        found.append((float(m["m10"] / m["m00"]), float(m["m01"] / m["m00"]), (int(x), int(y),
                    int(bw), int(bh)), float(area), mask))
    # the hole in an "o" is enclosed white too: drop anything inside a bigger region, since
    # that bigger region is the block the letter belongs to
    keep = []
    for cand in found:
        x, y, bw, bh = cand[2]
        if not any(o is not cand and o[2][0] <= x and o[2][1] <= y
                   and o[2][0] + o[2][2] >= x + bw and o[2][1] + o[2][3] >= y + bh
                   and o[3] > cand[3] for o in found):
            keep.append(cand)
    return keep


def _classify(mask, bbox) -> str:
    import cv2

    x, y, w, h = bbox
    cnts, _ = cv2.findContours(mask * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return "process"
    cnt = max(cnts, key=cv2.contourArea)
    fill = cv2.contourArea(cnt) / float(w * h)
    peri = cv2.arcLength(cnt, True)
    v = cv2.approxPolyDP(cnt, 0.03 * peri, True).reshape(-1, 2)

    if len(v) >= 6 and w / h > 1.2:
        r = h / 2.0                                    # a stadium is a rectangle + half discs
        want = ((w - h) * h + np.pi * r * r) / float(w * h)
        if abs(fill - want) < 0.10:
            return "terminal"
        return "process"
    if len(v) == 4 and fill < 0.70:
        top, bottom = v[v[:, 1].argmin()], v[v[:, 1].argmax()]
        left, right = v[v[:, 0].argmin()], v[v[:, 0].argmax()]

        def mid(val, target, span):
            return abs(val - target) <= max(4, 0.14 * span)

        # a diamond has exactly one corner per box edge, in the middle of it
        if (mid(top[0], x + w / 2, w) and mid(bottom[0], x + w / 2, w)
                and mid(left[1], y + h / 2, h) and mid(right[1], y + h / 2, h)):
            return "decision"
    if len(v) == 4 and fill < 0.95:                    # skewed: two corners share the top edge
        on_top = sum(1 for p in v if abs(p[1] - y) <= 3)
        on_bottom = sum(1 for p in v if abs(p[1] - (y + h)) <= 3)
        if on_top >= 2 and on_bottom >= 2:
            return "io"
    return "process"


def detect_shapes(image_path) -> List[Block]:
    """The blocks in an image, sorted in reading order (top to bottom, then left to right)."""
    import cv2

    _, gray, th = _binarize(image_path)
    blocks: List[Block] = []
    for cx, cy, bbox, area, mask in _regions(th):
        kind = _classify(mask, bbox)
        grown = cv2.dilate(mask, np.ones((9, 9), np.uint8))     # cover the outline as well
        cnts, _ = cv2.findContours(grown * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        poly: Tuple[Tuple[float, float], ...] = ()
        if cnts:
            hull = cv2.convexHull(max(cnts, key=cv2.contourArea))
            poly = tuple((float(p[0]), float(p[1])) for p in hull.reshape(-1, 2))
        blocks.append(Block(cx, cy, kind, text="", poly=poly, area=area))
    blocks.sort(key=lambda b: (round(b.cy / 24), b.cx))
    _read_text(blocks, gray)
    return blocks


def _read_text(blocks: List[Block], gray) -> None:
    """Fill in ``block.text`` if OCR exists, and leave it empty if it does not.

    Text is read one block at a time (crop the inside, OCR that) because a block holds three
    words at most, and the crop is what stops OCR inventing sentences.
    """
    if not ocr_available()[0]:
        return
    import cv2
    import pytesseract

    for b in blocks:
        xs = [p[0] for p in b.poly] or [b.cx]
        ys = [p[1] for p in b.poly] or [b.cy]
        x0, x1 = int(min(xs)) + 3, int(max(xs)) - 3
        y0, y1 = int(min(ys)) + 3, int(max(ys)) - 3
        if x1 <= x0 or y1 <= y0:
            continue
        crop = 255 - gray[y0:y1, x0:x1]                          # black text on white
        crop = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        try:
            b.text = pytesseract.image_to_string(crop, config="--psm 6").strip()
        except Exception:                                        # pragma: no cover
            b.text = ""


_OCR: Optional[Tuple[bool, str]] = None


def ocr_available() -> Tuple[bool, str]:
    """(ok, what to tell the user).  Cached, because it shells out to tesseract."""
    global _OCR
    if _OCR is None:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            _OCR = (True, "Tesseract is installed, so the words inside blocks are read too")
        except Exception:
            _OCR = (False, "no OCR on this machine (pip install pytesseract + install the "
                           "tesseract binary); photo mode recovers the blocks, the arrows and "
                           "the Yes/No sides, but leaves the text empty")
    return _OCR


# --------------------------------------------------------------------------- arrows

def _erase_blocks(th, blocks: Sequence[Block]):
    """Blank out every shape, so what is left is only the connectors.

    """
    import cv2

    mask = th.copy()
    for b in blocks:
        if b.poly:
            cv2.fillPoly(mask, [np.array(b.poly, np.int32)], 0)
    return mask


def _distance_field(ink):
    """For every pixel, how far it is from ink.  Computed once per picture, used 1000 times."""
    import cv2

    return cv2.distanceTransform(255 - ink, cv2.DIST_L2, 3)


def _coverage(dist, pts: Sequence[Tuple[float, float]], gap: float) -> float:
    """How much of a polyline runs on ink, as a fraction, with short blanks forgiven.

    A blank of a few pixels is a pen that lifted, or a Yes/No word painted over the line, so
    anything shorter than ``gap`` samples counts as covered.  Working from the distance field
    instead of the pixels themselves is what lets a wobbly photographed line pass.
    """
    h, w = dist.shape
    flags: List[bool] = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        steps = max(2, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5))
        for i in range(steps + 1):
            x = x0 + (x1 - x0) * i / steps
            y = y0 + (y1 - y0) * i / steps
            flags.append(bool(dist[int(round(y)) % h, int(round(x)) % w] <= 3.0))
    if not flags:
        return 0.0
    i = 0
    while i < len(flags):
        if flags[i]:
            i += 1
            continue
        j = i
        while j < len(flags) and not flags[j]:
            j += 1
        if j - i <= gap:
            for k in range(i, j):
                flags[k] = True
        i = j
    return sum(flags) / float(len(flags))


def _boundary_point(block: Block, toward: Tuple[float, float]) -> Tuple[float, float]:
    """Walk out of a shape towards a point and stop where its outline is."""
    import cv2

    if len(block.poly) < 3:
        return (block.cx, block.cy)
    poly = np.array(block.poly, np.float32)
    dx, dy = toward[0] - block.cx, toward[1] - block.cy
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / length, dy / length
    t = 0.0
    while t < length:
        pt = (block.cx + ux * t, block.cy + uy * t)
        if cv2.pointPolygonTest(poly, pt, False) < 0:
            return pt
        t += 1.5
    return (block.cx + ux * (length - 2), block.cy + uy * (length - 2))


def _facing(block: Block, at: Tuple[float, float], toward: Tuple[float, float]) -> bool:
    """True when an anchor points the way the line then goes.

    Without this every combination of a side of one box with a side of another box is a
    candidate, and a route that leaves the bottom of a box and comes back into its neighbour
    from underneath is only a few pixels of ink away from looking real.
    """
    if at == (block.cx, block.cy):
        return True
    ox, oy = at[0] - block.cx, at[1] - block.cy
    dx, dy = toward[0] - at[0], toward[1] - at[1]
    return (ox * dx + oy * dy) > 0.0


def _crosses_other(route, a: Block, b: Block, blocks: Sequence[Block]) -> bool:
    """An arrow does not run through a third shape.  If it seems to, it is not that arrow."""
    import cv2

    for c in blocks:
        if c is a or c is b or len(c.poly) < 3:
            continue
        cp = np.array(c.poly, np.float32)
        inside = 0
        for (x0, y0), (x1, y1) in zip(route, route[1:]):
            steps = max(2, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5))
            for i in range(steps + 1):
                x, y = x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps
                if cv2.pointPolygonTest(cp, (x, y), False) > 0:
                    inside += 1
                    if inside > 3:
                        return True
                else:
                    inside = 0
    return False


def _length(pts) -> float:
    return sum(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in zip(pts, pts[1:]))


def _density(ink, pt: Tuple[float, float]) -> float:
    h, w = ink.shape
    x0, y0 = int(max(0, min(w - 1, pt[0] - 11))), int(max(0, min(h - 1, pt[1] - 11)))
    x1, y1 = int(max(0, min(w, pt[0] + 11))), int(max(0, min(h, pt[1] + 11)))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float(ink[y0:y1, x0:x1].mean())


_DIRS = ((0, -1), (0, 1), (-1, 0), (1, 0), (0, 0))


def _anchors(block: Block) -> List[Tuple[float, float]]:
    """Where an arrow may leave or enter a shape: the four sides, plus the way it faces.

    A hand-drawn arrow does not run between centres; it leaves a corner or a side.  So the
    hypothesis has to be tried from each plausible exit to each plausible entry, otherwise
    every diagonal branch arrow is looked for in the wrong place and comes back as missing.
    """
    pts = []
    for dx, dy in _DIRS:
        if (dx, dy) == (0, 0):
            continue
        pts.append(_boundary_point(block, (block.cx + 80 * dx, block.cy + 80 * dy)))
    return pts


def _routes(a: Block, b: Block, ink) -> List[List[Tuple[float, float]]]:
    """Candidate ways to get from a to b.

    The same families the renderer uses: a straight line between two anchors, and the two
    right-angle routes, plus for a back edge the way round the left or the right of the
    drawing.  Looking for exactly the shapes that are drawn is what keeps this cheap.
    """
    outs, ins = _anchors(a), _anchors(b)
    seen: List[List[Tuple[float, float]]] = []
    for pa in outs:
        for pb in ins:
            if pa[1] > pb[1] + 4:                 # never look *up* a straight line
                continue
            seen.append([pa, pb])
    a_bot, b_top = _boundary_point(a, (a.cx, a.cy + 200)), _boundary_point(b, (b.cx, b.cy - 200))
    mid_y = (a_bot[1] + b_top[1]) / 2
    b_side = _boundary_point(b, (a.cx, b.cy))
    seen.append([a_bot, (a.cx, mid_y), (b.cx, mid_y), b_top])
    seen.append([a_bot, (b.cx, a_bot[1]), b_top])
    seen.append([a_bot, (a.cx, b.cy), b_side])       # down, then across into the side
    for off in (max(a.cx, b.cx) + 100, min(a.cx, b.cx) - 100):
        a_side = _boundary_point(a, (off, a.cy))
        b_away = _boundary_point(b, (off, b.cy))
        seen.append([a_side, (off, a_side[1]), (off, b_away[1]), b_away])
    if b.cy >= a.cy - 12:
        return seen
    h, w = ink.shape
    xs_a = [p[0] for p in a.poly] or [a.cx]
    xs_b = [p[0] for p in b.poly] or [b.cx]
    for x in (max(max(xs_a), max(xs_b)) + 26, min(min(xs_a), min(xs_b)) - 26):
        if 1 < x < w - 1:
            pa = _boundary_point(a, (x, a.cy))
            pb = _boundary_point(b, (x, b.cy))
            seen.append([pa, (x, pa[1]), (x, pb[1]), pb])
    return seen


def detect_connections(image_path, blocks: Sequence[Block], min_cover: float = 0.55
                       ) -> List[Tuple[Block, Block, float]]:
    """Plausible arrows as ``(from block, to block, confidence)``.

    Two stages, because each one alone is weak.  Connected components say *which two blocks a
    stroke actually joins* — that part cannot invent an edge — but a stroke that runs behind a
    label may not touch anything at one end.  Route scoring says whether the ink really lies on
    a legal connector between a pair, and which end has the arrowhead.  So: take the pairs the
    components suggest, then keep only the ones the geometry agrees with.
    """
    import cv2

    _, _, th = _binarize(image_path)
    ink = cv2.dilate(_erase_blocks(th, blocks), np.ones((3, 3), np.uint8))
    dist = _distance_field(ink)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    ends = _component_ends(lab, stats, n)

    found: List[Tuple[Block, Block, float]] = []
    for a in blocks:
        for b in blocks:
            if a is b:
                continue
            best, head = 0.0, None
            for route in _routes(a, b, ink):
                if not _facing(a, route[0], route[1]) or not _facing(b, route[-1], route[-2]):
                    continue
                if _crosses_other(route, a, b, blocks):
                    continue
                cov = _coverage(dist, route, BLOCK_GAP)
                if cov > best:
                    best, head = cov, route
            if best < min_cover or head is None or _length(head) < 14:
                continue
            cid = _label_at(lab, head)
            pair = ends.get(cid)
            if pair is None:
                continue
            e1, e2 = pair
            # the stroke has to *start* at the source block.  Only that end is checked: the
            # far end is where two or three arrows legitimately meet, and a component can
            # contain several of them, which is exactly what a converging chart looks like.
            if not (_near(e1, head[0], 26) or _near(e2, head[0], 26)):
                continue
            tail_end, head_end = ((e1, e2) if _dist_pt(e1, head[0]) <= _dist_pt(e2, head[0])
                                  else (e2, e1))
            # an arrowhead is a filled wedge, so the stroke is fatter at that end; judged on
            # the stroke's own ends because the route ends inside the erased band around a block
            if _length(head) < 44:
                # too short for a head to be visible in: fall back on the convention that
                # control flows down the page, and left to right along a row
                if (a.cy, a.cx) >= (b.cy, b.cx):
                    continue
            elif _density(ink, head_end) <= _density(ink, tail_end):
                continue                                # no arrowhead at the far end
            found.append((a, b, best))
    return found


def _component_ends(lab, stats, n) -> Dict[int, Tuple[Tuple[float, float], Tuple[float, float]]]:
    """The two far-apart ends of every ink stroke."""
    out: Dict[int, Tuple[Tuple[float, float], Tuple[float, float]]] = {}
    for i in range(1, n):
        if int(stats[i][4]) < 60:
            continue                                    # a dot, or a leftover letter
        ys, xs = np.nonzero(lab == i)
        pts = np.stack([xs, ys], 1).astype(np.float32)
        if len(pts) > 900:
            pts = pts[np.linspace(0, len(pts) - 1, 900).astype(int)]
        d = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
        i1, i2 = np.unravel_index(int(d.argmax()), d.shape)
        out[i] = ((float(pts[i1][0]), float(pts[i1][1])), (float(pts[i2][0]), float(pts[i2][1])))
    return out


def _label_at(lab, route) -> int:
    """Which stroke this route rides on: the component label at its half-way point.

    Half-way *along the line*, not the middle vertex of the polyline, and with a small search
    radius, because a route may pass a Yes/No word where the ink is deliberately not drawn.
    """
    total = _length(route) / 2.0
    acc = 0.0
    mid = route[0]
    for a, b in zip(route, route[1:]):
        seg = _dist_pt(a, b)
        if acc + seg >= total:
            t = 0.0 if seg == 0 else (total - acc) / seg
            mid = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            break
        acc += seg
    y, x = int(round(mid[1])), int(round(mid[0]))
    h, w = lab.shape
    if not (0 <= y < h and 0 <= x < w):
        return 0
    if lab[y, x] != 0:
        return int(lab[y, x])
    r = 14
    near = [(lab[yy, xx], (yy - y) ** 2 + (xx - x) ** 2)
            for yy in range(max(0, y - r), min(h, y + r + 1))
            for xx in range(max(0, x - r), min(w, x + r + 1)) if lab[yy, xx] != 0]
    return int(min(near, key=lambda t: t[1])[0]) if near else 0


def _near(a: Tuple[float, float], b: Tuple[float, float], r: float) -> bool:
    return _dist_pt(a, b) <= r


def _dist_to_block(pt, b: Block) -> float:
    """Distance from a point to a block's *outline*, not to its corner list.

    The difference decides whether this works at all: an arrow that stops in the middle of a
    box edge is 0 px from the box and 40 px from its corners.
    """
    pts = list(b.poly)
    if len(pts) < 2:
        return 1e18
    px, py = pt
    best = 1e18
    for k in range(len(pts)):
        (ax, ay), (bx, by) = pts[k], pts[(k + 1) % len(pts)]
        vx, vy = bx - ax, by - ay
        L = vx * vx + vy * vy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L))
        cx, cy = ax + t * vx, ay + t * vy
        best = min(best, ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5)
    return best


def _nearest_block(pt, blocks: Sequence[Block]) -> Optional[Block]:
    best, bestd = None, 1e18
    for b in blocks:
        dd = _dist_to_block(pt, b)
        if dd < bestd:
            best, bestd = b, dd
    return best if bestd <= 60.0 else None


def _dist_pt(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


# --------------------------------------------------------------------------- the whole chart

_KIND = {"terminal": "start", "io": "output", "process": "process", "decision": "decision"}


def detect_chart(image_path, name: Optional[str] = None) -> Tuple[Flowchart, List[str]]:
    """Picture in, :class:`Flowchart` out, plus notes about what could not be recovered.

    The result is *structural*: the right number of blocks, in the right places, with the right
    types and the right arrows.  Text is a bonus where OCR exists.
    """
    notes: List[str] = []
    blocks = detect_shapes(image_path)
    if len(blocks) < 2:
        raise Flow2CodeError(f"found {len(blocks)} block(s) in {Path(image_path).name}; a "
                             f"flowchart needs at least a Start shape and an End shape")
    ok, msg = ocr_available()
    if not ok:
        notes.append(msg)

    ids: Dict[int, str] = {id(b): f"n{i}" for i, b in enumerate(blocks, start=1)}
    nodes = [Node(ids[id(b)], _KIND[b.type], b.text, b.cx, b.cy) for b in blocks]
    _orient(nodes, notes)
    _fix_io(nodes, notes)

    conf: Dict[Tuple[str, str], float] = {}
    for src, dst, c in detect_connections(image_path, blocks):
        key = (ids[id(src)], ids[id(dst)])
        conf[key] = max(conf.get(key, 0.0), c)
    edges = [Edge(s, d) for (s, d) in conf]
    if not edges:
        notes.append("no connector reached a block; arrows have to touch the shape they "
                     "belong to")
    _label_decisions(nodes, edges, notes)

    fc = Flowchart(name=name or Path(image_path).stem, nodes=nodes, edges=edges)
    return fc, notes


def _orient(nodes: List[Node], notes: List[str]) -> None:
    """Start and End are drawn as the same shape, so which is which needs a rule."""
    term = sorted((n for n in nodes if n.type == "start"), key=lambda n: (n.y, n.x))
    if not term:
        return
    for n in term:
        low = (n.text or "").strip().lower()
        if low.startswith(("end", "stop", "finish", "halt")):
            n.type = "end"
    if all(n.type == "start" for n in term):
        if len(term) == 1:
            notes.append("one terminator found, treated as Start; add the End in the editor")
        else:
            term[0].type = "start"          # the topmost is Start, every other one is an End
            for n in term[1:]:
                n.type = "end"
    if not any(n.type == "start" for n in nodes):
        term[0].type = "start"


def _fix_io(nodes: List[Node], notes: List[str]) -> None:
    """A parallelogram only says 'data'; which way it points comes from the words."""
    io = [n for n in nodes if n.type in ("input", "output")]
    read = [n for n in io if (n.text or "").strip().lower().startswith(
        ("read", "input", "get", "enter"))]
    for n in read:
        n.type = "input"
    if io and not read and not any(n.text for n in io):
        notes.append("no OCR, so the data shapes are all marked Print; switch the ones that "
                     "should be Read in the editor")


def _label_decisions(nodes: Sequence[Node], edges: List[Edge], notes: List[str]) -> None:
    by_id = {n.id: n for n in nodes}
    for n in nodes:
        if n.type != "decision":
            continue
        out = [e for e in edges if e.src == n.id]
        if len(out) == 1:                      # only one branch came back; label it by side
            tgt = by_id.get(out[0].dst)
            out[0].label = "yes" if tgt is not None and tgt.x < n.x else "no"
            notes.append(f"decision {n.id}: only the {out[0].label} arrow was found, the other "
                         f"one is left for the editor")
            continue
        if len(out) != 2:
            notes.append(f"decision {n.id} has {len(out)} outgoing arrows, so Yes/No were left "
                         f"unset and the editor will ask for them")
            continue
        for e in out:
            tgt = by_id.get(e.dst)
            if tgt is not None:
                e.label = "yes" if tgt.x < n.x - 4 else "no"
        if {e.label for e in out} != {"yes", "no"}:        # both arrows left the same side
            out[-1].label = "no"
            notes.append(f"decision {n.id}: both arrows go the same way, so the second was "
                         f"taken as No - check it in the editor")

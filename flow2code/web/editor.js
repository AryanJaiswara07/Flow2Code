/* The canvas.  No framework, no build step: an SVG board that the app hands a chart
 * dictionary to and gets one back from.  Every interaction a flowchart needs is here —
 * place, drag, resize, connect, label, annotate, undo, pan, zoom.
 *
 * The editor never talks to the server.  It mutates its own model and fires a `change`
 * event; app.js decides what to do about that.
 */

const SVGNS = "http://www.w3.org/2000/svg";
const GRID = 10;
const MIN = { w: 90, h: 44 };

function el(tag, attrs = {}, kids = []) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const kid of [].concat(kids)) if (kid) node.appendChild(kid);
  return node;
}

/* One hidden canvas does the text measuring, so the words wrap on the same columns as
 * they do in the PNG the server draws. */
const measure = document.createElement("canvas").getContext("2d");
const BODY = "500 14px ui-sans-serif, system-ui, 'Segoe UI', sans-serif";
measure.font = BODY;

function wrap(text, maxWidth) {
  const words = String(text || "").split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const trial = line ? `${line} ${word}` : word;
    if (measure.measureText(trial).width <= maxWidth || !line) {
      if (measure.measureText(trial).width > maxWidth && !line) {
        // a single long word: let it hang, the shape is the smaller thing
        lines.push(word);
        line = "";
        continue;
      }
      line = trial;
    } else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [""];
}

/* The symbol for each shape, in one path.  The palette previews, the canvas and the server's
 * PNG renderer all draw from this geometry, so a shape never looks different in two
 * places. */
export function outlinePath(shape, w, h) {
  const x0 = -w / 2, y0 = -h / 2, x1 = w / 2, y1 = h / 2;
  switch (shape) {
    case "terminal": {                       // stadium: the ends are full half circles
      const r = h / 2;
      return `M${x0 + r},${y0} H${x1 - r} A${r},${r} 0 0 1 ${x1 - r},${y1}`
        + ` H${x0 + r} A${r},${r} 0 0 1 ${x0 + r},${y0} Z`;
    }
    case "diamond": return `M0,${y0} L${x1},0 L0,${y1} L${x0},0 Z`;
    case "io": {                              // data: a parallelogram leaning right
      const s = Math.min(20, w * 0.13);
      return `M${x0 + s},${y0} H${x1} L${x1 - s},${y1} H${x0} Z`;
    }
    case "manual": {                          // a person writes on it: slanted bottom edge
      const s = Math.min(22, w * 0.16);
      return `M${x0},${y0} H${x1} L${x1 - s},${y1} H${x0 + s} Z`;
    }
    case "hexagon": {                         // preparation
      const s = Math.min(26, w * 0.18);
      return `M${x0 + s},${y0} H${x1 - s} L${x1},0 L${x1 - s},${y1} H${x0 + s} L${x0},0 Z`;
    }
    case "document": {                        // a page with a curled foot
      const amp = Math.min(9, h * 0.22);
      return `M${x0},${y0} H${x1} V${y1 - amp}`
        + ` C${x1 - w * 0.18},${y1 + amp} ${x0 + w * 0.18},${y1 + amp} ${x0},${y1 - amp} Z`;
    }
    case "database": {                        // a drum: body plus the rim ellipse
      const r = Math.min(12, h * 0.2);
      return `M${x0},${y0 + r} V${y1 - r} A${w / 2},${r} 0 0 1 ${x1},${y1 - r} V${y0 + r} Z`
        + ` M${x0},${y0 + r} A${w / 2},${r} 0 0 1 ${x1},${y0 + r}`
        + ` A${w / 2},${r} 0 0 1 ${x0},${y0 + r} Z`;
    }
    case "circle": {                          // on-page connector
      const r = Math.min(w, h) / 2;
      return `M${-r},0 A${r},${r} 0 1 0 ${r},0 A${r},${r} 0 1 0 ${-r},0 Z`;
    }
    case "pentagon": {                        // off-page connector
      const s = Math.min(16, h * 0.28);
      return `M${x0},${y0} H${x1} V${y1 - s} L0,${y1} L${x0},${y1 - s} Z`;
    }
    case "delay": {                           // a box with a dome on the right
      const r = h / 2;
      return `M${x0},${y0} H${x1 - r} A${r},${r} 0 0 1 ${x1 - r},${y1} H${x0} Z`;
    }
    default: return `M${x0},${y0} H${x1} V${y1} H${x0} Z`;
  }
}


/* How far the side anchor of a leaning shape sits inside its bounding box: a data
 * parallelogram and a manual trapezoid are narrowest at the middle of their height. */
function sideInset(shape, w) {
  if (shape === "io") return Math.min(20, w * 0.13) / 2;
  if (shape === "manual") return Math.min(22, w * 0.16) / 2;
  return 0;
}


export class ChartEditor extends EventTarget {
  constructor(stage, meta) {
    super();
    this.stage = stage;
    this.kinds = Object.fromEntries(meta.kinds.map((k) => [k.type, k]));
    this.chart = { name: "untitled", note: "", stdin: "", nodes: [], edges: [], notes: [] };
    this.sel = null;                 // {kind:'node'|'edge'|'note', id}
    this.view = { k: 1, tx: 40, ty: 30 };
    this.snap = true;
    this.history = [];
    this.future = [];
    this._drag = null;
    this._buildDom();
    this._bind();
  }

  /* ------------------------------------------------------------ model in / out */
  setChart(chart) {
    this.chart = {
      name: chart.name || "untitled",
      note: chart.note || "",
      stdin: chart.stdin || "",
      nodes: (chart.nodes || []).map((n) => ({ ...n, x: +n.x || 0, y: +n.y || 0 })),
      edges: (chart.edges || []).map((e) => ({
        from: e.from ?? e.src, to: e.to ?? e.dst, label: e.label || "" })),
      notes: (chart.notes || []).map((t) => ({ text: t.text || "", x: +t.x || 0, y: +t.y || 0 })),
    };
    this.history = [];
    this.future = [];
    this.sel = null;
    this.render();
    this.fit({ pad: 60 });
    this._changed("load");                           // so the app re-checks whatever arrived
  }

  /* swap the whole chart in, keeping the undo stack (used by Tidy and by an import) */
  replace(chart) {
    this._push();
    const keep = this.sel;
    this.chart = { ...this.chart, ...JSON.parse(JSON.stringify(chart)) };
    this.sel = keep && this.byId(keep.id) ? keep : null;
    this.render();
    this._changed("replace");
  }

  getChart() {
    return JSON.parse(JSON.stringify(this.chart));
  }

  sizeOf(node) {
    const kind = this.kinds[node.type] || this.kinds.process;
    return { w: +node.w > 0 ? +node.w : kind.w, h: +node.h > 0 ? +node.h : kind.h };
  }

  bounds() {
    const pts = [];
    for (const n of this.chart.nodes) {
      const s = this.sizeOf(n);
      pts.push([n.x - s.w / 2, n.y - s.h / 2], [n.x + s.w / 2, n.y + s.h / 2]);
    }
    for (const t of this.chart.notes) pts.push([t.x, t.y], [t.x + 170, t.y + 46]);
    if (!pts.length) return { x0: 0, y0: 0, x1: 400, y1: 300 };
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
  }

  /* ------------------------------------------------------------ mutations */
  add(kind, at) {
    this._push();
    const node = { id: this._freeId(kind), type: kind, text: this._defaultText(kind),
                   x: at.x, y: at.y };
    this.chart.nodes.push(node);
    this.sel = { kind: "node", id: node.id };
    this.render();
    this._changed("add");
    return node;
  }

  update(id, patch) {
    const node = this.chart.nodes.find((n) => n.id === id);
    if (!node) return;
    this._push();
    Object.assign(node, patch);
    this.render();
    this._changed("edit");
  }

  setNoteText(index, text) {
    this._push();
    this.chart.notes[index].text = text;
    this.render();
    this._changed("edit");
  }

  addNote(at) {
    this._push();
    this.chart.notes.push({ text: "note", x: at.x, y: at.y });
    this.render();
    this._changed("add");
  }

  remove(id) {
    this._push();
    if (this.sel?.kind === "edge") {
      const { from, to } = this.chart.edges[this.sel.id];
      this.chart.edges = this.chart.edges.filter((e) => !(e.from === from && e.to === to));
    } else if (this.sel?.kind === "note") {
      this.chart.notes.splice(this.sel.id, 1);
    } else {
      this.chart.nodes = this.chart.nodes.filter((n) => n.id !== id);
      this.chart.edges = this.chart.edges.filter((e) => e.from !== id && e.to !== id);
    }
    this.sel = null;
    this.render();
    this._changed("delete");
  }

  connect(from, to) {
    if (from === to) return false;
    if (this.chart.edges.some((e) => e.from === from && e.to === to)) return false;
    this._push();
    this.chart.edges.push({ from, to, label: "" });
    this._yesNo(from);                                // a decision's first two arrows
    this.render();
    this._changed("connect");
    return true;
  }

  _yesNo(from) {
    const out = this.chart.edges.filter((e) => e.from === from);
    if (out.length === 2 && !out[0].label && !out[1].label) {
      out[0].label = "yes";
      out[1].label = "no";
    }
  }

  labelEdge(index, label) {
    this._push();
    this.chart.edges[index].label = label;
    this.render();
    this._changed("label");
  }

  byId(id) { return this.chart.nodes.find((n) => n.id === id) || null; }

  /* the two fields that live beside the drawing */
  setName(name) { this.chart.name = name; this._changed("name"); }
  setStdin(text) { this.chart.stdin = text; this._changed("stdin"); }

  _freeId(kind) {
    const stem = (kind || "n").replace(/[^a-z]/g, "").slice(0, 1) || "n";
    let i = 1;
    const taken = new Set(this.chart.nodes.map((n) => n.id));
    while (taken.has(`${stem}${i}`)) i += 1;
    return `${stem}${i}`;
  }

  _defaultText(kind) {
    return ({ start: "Start", end: "End", input: "Read n", output: "Print answer",
      decision: "n > 0?", process: "x = x + 1", document: "write_row()",
      database: "rows = store.all()", manual: "sign the sheet", preparation: "i = 0",
      delay: "sleep(1)", connector: "A", offpage: "continue" })[kind] || "";
  }

  /* ------------------------------------------------------------ history */
  _push() {
    this.history.push(JSON.stringify(this.chart));
    if (this.history.length > 60) this.history.shift();
    this.future = [];
  }

  undo() {
    if (!this.history.length) return false;
    this.future.push(JSON.stringify(this.chart));
    this.chart = JSON.parse(this.history.pop());
    this.sel = null;
    this.render();
    this._changed("undo");
    return true;
  }

  redo() {
    if (!this.future.length) return false;
    this.history.push(JSON.stringify(this.chart));
    this.chart = JSON.parse(this.future.pop());
    this.render();
    this._changed("redo");
    return true;
  }

  _changed(why) {
    this.dispatchEvent(new CustomEvent("change", { detail: { why, chart: this.getChart() } }));
  }

  /* ------------------------------------------------------------ view */
  zoomBy(factor, centre) {
    const k = Math.min(2.5, Math.max(0.35, this.view.k * factor));
    const box = this.stage.getBoundingClientRect();
    const at = centre || { x: box.width / 2, y: box.height / 2 };
    this.view.tx = at.x - (at.x - this.view.tx) * (k / this.view.k);
    this.view.ty = at.y - (at.y - this.view.ty) * (k / this.view.k);
    this.view.k = k;
    this._applyView();
  }

  fit(opts = {}) {
    const pad = opts.pad ?? 40;
    const b = this.bounds();
    const box = this.stage.getBoundingClientRect();
    const w = Math.max(1, b.x1 - b.x0), h = Math.max(1, b.y1 - b.y0);
    const k = Math.min(2.5, Math.max(0.35, Math.min((box.width - pad * 2) / w, (box.height - pad * 2) / h)));
    this.view.k = k;
    this.view.tx = (box.width - w * k) / 2 - b.x0 * k;
    this.view.ty = (box.height - h * k) / 2 - b.y0 * k;
    this._applyView();
  }

  centreOn(id) {
    const node = this.byId(id);
    if (!node) return;
    const box = this.stage.getBoundingClientRect();
    this.view.tx = box.width / 2 - node.x * this.view.k;
    this.view.ty = box.height / 2 - node.y * this.view.k;
    this._applyView();
  }

  _applyView() {
    this.world.setAttribute("transform",
      `translate(${this.view.tx},${this.view.ty}) scale(${this.view.k})`);
    this.stage.dispatchEvent(new CustomEvent("viewport", { detail: { ...this.view } }));
  }

  toWorld(point) {
    const box = this.stage.getBoundingClientRect();
    return { x: (point.clientX - box.left - this.view.tx) / this.view.k,
             y: (point.clientY - box.top - this.view.ty) / this.view.k };
  }

  toScreen(world) {
    return { x: world.x * this.view.k + this.view.tx, y: world.y * this.view.k + this.view.ty };
  }

  snapTo(v) { return this.snap && !this.altKey ? Math.round(v / GRID) * GRID : Math.round(v); }

  /* ------------------------------------------------------------ dom */
  _buildDom() {
    // the stage keeps its overlay (hint, toolbar); the board is just the first child
    this.svg = el("svg", { class: "board" });
    this.svg.appendChild(el("defs", {}, [
      el("marker", { id: "tip", viewBox: "0 0 10 10", refX: 9, refY: 5,
                     markerWidth: 7.5, markerHeight: 7.5, orient: "auto-start-reverse" },
        [el("path", { d: "M0,1 L9,5 L0,9 Z", class: "tip" })]),
      el("marker", { id: "tip-on", viewBox: "0 0 10 10", refX: 9, refY: 5,
                     markerWidth: 7.5, markerHeight: 7.5, orient: "auto-start-reverse" },
        [el("path", { d: "M0,1 L9,5 L0,9 Z", class: "tip-on" })]),
      el("pattern", { id: "grid", width: GRID * 2, height: GRID * 2, patternUnits: "userSpaceOnUse" },
        [el("path", { d: `M${GRID * 2} 0 L0 0 0 ${GRID * 2}`, fill: "none",
                      stroke: "rgba(20,24,22,.07)", "stroke-width": 1 })]),
    ]));
    this.sheet = el("rect", { class: "sheet", x: -4000, y: -4000, width: 9000, height: 9000,
                              fill: "url(#grid)" });
    this.world = el("g", { class: "world" });
    this.lEdge = el("g", { class: "edges" });
    this.lNode = el("g", { class: "nodes" });
    this.lOver = el("g", { class: "overlay" });
    this.world.append(this.lEdge, this.lNode, this.lOver);
    this.svg.append(this.sheet, this.world);
    this.stage.prepend(this.svg);
    this.svg.style.touchAction = "none";
  }

  /* ------------------------------------------------------------ draw */
  render() {
    this.lEdge.replaceChildren(...this.chart.edges.map((e, i) => this._edgeGroup(e, i)));
    this.lNode.replaceChildren(...this.chart.nodes.map((n) => this._nodeGroup(n)));
    this.lOver.replaceChildren(...this.chart.notes.map((t, i) => this._noteGroup(t, i)),
      ...(this.sel?.kind === "node" ? this._handles(this.byId(this.sel.id)) : []));
    const b = this.bounds();
    this.sheet.setAttribute("x", Math.min(-4000, b.x0 - 2000));
    this.sheet.setAttribute("y", Math.min(-4000, b.y0 - 2000));
  }

  _nodeGroup(node) {
    const kind = this.kinds[node.type] || this.kinds.process;
    const { w, h } = this.sizeOf(node);
    const on = this.sel?.kind === "node" && this.sel.id === node.id;
    const flagged = this.flagged?.has(node.id);
    const g = el("g", { class: `node${on ? " on" : ""}${flagged ? " bad" : ""}`,
                       "data-role": "node", "data-id": node.id,
                       transform: `translate(${node.x},${node.y})` });
    g.appendChild(el("path", { d: this._outline(kind.shape, w, h), class: "skin",
                               "vector-effect": "non-scaling-stroke" }));
    const lines = wrap(node.text, w - 22);
    const startY = -((Math.min(lines.length, 3) - 1) * 17) / 2;
    lines.slice(0, 3).forEach((line, i) => {
      g.appendChild(el("text", { x: 0, y: startY + i * 17, class: "cap", "text-anchor": "middle" },
        [document.createTextNode(line)]));
    });
    if (lines.length > 3) {
      g.appendChild(el("text", { x: 0, y: startY + 3 * 17, class: "more", "text-anchor": "middle" },
        [document.createTextNode("…")]));
    }
    if (kind.code === "condition") {
      const yes = this.chart.edges.filter((e) => e.from === node.id);
      if (yes.length && yes.every((e) => !e.label)) {
        g.appendChild(el("text", { x: 0, y: h / 2 + 15, class: "ask", "text-anchor": "middle" },
          [document.createTextNode("label the two arrows")]));
      }
    }
    return g;
  }

  _outline(shape, w, h) { return outlinePath(shape, w, h); }

  _noteGroup(note, index) {
    const on = this.sel?.kind === "note" && this.sel.id === index;
    const lines = wrap(note.text, 150);
    const h = Math.max(44, 22 + lines.length * 15);
    const g = el("g", { class: `note${on ? " on" : ""}`, "data-role": "note", "data-id": index,
                        transform: `translate(${note.x},${note.y})` });
    g.appendChild(el("path", { d: `M0,0 H170 V${h - 10} L160,${h} H0 Z`, class: "paper" }));
    lines.slice(0, 4).forEach((line, i) => {
      g.appendChild(el("text", { x: 10, y: 18 + i * 15, class: "note-cap" },
        [document.createTextNode(line)]));
    });
    return g;
  }

  _handles(node) {
    if (!node) return [];
    const { w, h } = this.sizeOf(node);
    const out = [];
    for (const [dx, dy, dir] of [[-w / 2, -h / 2, "nw"], [w / 2, -h / 2, "ne"],
                                 [w / 2, h / 2, "se"], [-w / 2, h / 2, "sw"]]) {
      out.push(el("rect", { class: "sz", x: node.x + dx - 4, y: node.y + dy - 4, width: 8, height: 8,
                            "data-role": "size", "data-dir": dir, "data-id": node.id }));
    }
    for (const [dx, dy, side] of [[0, -h / 2, "top"], [w / 2, 0, "right"],
                                  [0, h / 2, "bottom"], [-w / 2, 0, "left"]]) {
      out.push(el("circle", { class: "port", cx: node.x + dx, cy: node.y + dy, r: 6,
                              "data-role": "port", "data-side": side, "data-id": node.id }));
    }
    return out;
  }

  /* ------------------------------------------------------------ edges */
  ports(node) {
    const { w, h } = this.sizeOf(node);
    const shape = (this.kinds[node.type] || {}).shape;
    if (shape === "circle") {
      const r = Math.min(w, h) / 2;
      return { top: [node.x, node.y - r], bottom: [node.x, node.y + r],
               left: [node.x - r, node.y], right: [node.x + r, node.y] };
    }
    const inset = sideInset(shape, w);          // the slant on a data or manual shape
    return { top: [node.x, node.y - h / 2], bottom: [node.x, node.y + h / 2],
             left: [node.x - w / 2 + inset, node.y], right: [node.x + w / 2 - inset, node.y] };
  }

  /* Which side of each shape the arrow leaves and arrives at.  The rule a reader expects:
   * down the page for the main path, out of the side for a decision's two branches, and a
   * loop runs down a clear lane beside the chart instead of through it. */
  route(edge) {
    const a = this.byId(edge.from), b = this.byId(edge.to);
    if (!a || !b) return { pts: [], mid: [0, 0] };
    const pa = this.ports(a), pb = this.ports(b);
    const dx = b.x - a.x, dy = b.y - a.y;
    if (dy < -30) {                                      // back up the page: take a lane
      // a loop runs beside the drawing, never through it: of the two sides, the one that is
      // clear of every block, and of those the shorter way round
      const b0 = this.bounds();
      const ways = [
        { side: "left", lane: Math.min(b0.x0, a.x, b.x) - 56 },
        { side: "right", lane: Math.max(b0.x1, a.x, b.x) + 56 },
      ].map((c) => {
        c.pts = [pa[c.side], [c.lane, pa[c.side][1]], [c.lane, pb[c.side][1]], pb[c.side]];
        c.len = c.pts.slice(1).reduce((t, q, i) => t + Math.hypot(q[0] - c.pts[i][0], q[1] - c.pts[i][1]), 0);
        c.blocked = this._laneCrosses(c.lane, pa[c.side], pb[c.side], [a.id, b.id]);
        return c;
      });
      const free = ways.filter((c) => !c.blocked);
      const pick = (free.length ? free : ways).slice().sort((x, y) => x.len - y.len)[0];
      return { pts: pick.pts, mid: this._mid(pick.pts), back: true };
    }
    if (this.kinds[a.type]?.out === 2 && Math.abs(dx) > 60) {     // a decision's Yes / No
      const side = dx > 0 ? "right" : "left";
      const endSide = Math.abs(dy) > 40 ? (dy > 0 ? "top" : "bottom") : (side === "right" ? "left" : "right");
      return this._elbow(pa[side], side, pb[endSide], endSide);
    }
    const down = dy > 20, across = Math.abs(dx) > 20;
    if (down && Math.abs(dy) >= Math.abs(dx) * 0.5) {
      const startSide = "bottom", endSide = Math.abs(dx) > (this.sizeOf(a).w + this.sizeOf(b).w) / 2
        ? (dx > 0 ? "left" : "right") : "top";
      return this._elbow(pa[startSide], startSide, pb[endSide], endSide);
    }
    if (across) {
      const startSide = dx > 0 ? "right" : "left";
      const endSide = down ? "top" : (dx > 0 ? "left" : "right");
      return this._elbow(pa[startSide], startSide, pb[endSide], endSide);
    }
    return this._elbow(pa.bottom, "bottom", pb.top, "top");
  }

  /* Does a loop lane at this x, running between the two side anchors, cut through a block? */
  _laneCrosses(lane, from, to, skip) {
    const top = Math.min(from[1], to[1]), bottom = Math.max(from[1], to[1]);
    for (const n of this.chart.nodes) {
      if (skip.includes(n.id)) continue;
      const s = this.sizeOf(n);
      const x0 = n.x - s.w / 2 - 6, x1 = n.x + s.w / 2 + 6;
      const y0 = n.y - s.h / 2 - 6, y1 = n.y + s.h / 2 + 6;
      if (lane > x0 && lane < x1 && bottom > y0 && top < y1) return true;
      const y = from[1] === to[1] ? from[1] : null;    // the two stubs, if they are horizontal
      if (y !== null && Math.max(from[0], to[0]) > x0 && Math.min(from[0], to[0]) < x1
        && y > y0 && y < y1) return true;
    }
    return false;
  }

  /* Legs are axis-aligned, and the last one arrives perpendicular to the side it enters —
   * otherwise the arrowhead points along the edge instead of into the shape. */
  _elbow(start, startSide, end, endSide) {
    const out = startSide === "top" || startSide === "bottom";
    const into = endSide === "top" || endSide === "bottom";
    let pts;
    if (out && into) {
      pts = Math.abs(start[0] - end[0]) < 3 ? [start, end]
        : [start, [start[0], (start[1] + end[1]) / 2], [end[0], (start[1] + end[1]) / 2], end];
    } else if (!out && !into) {
      pts = Math.abs(start[1] - end[1]) < 3 ? [start, end]
        : [start, [(start[0] + end[0]) / 2, start[1]], [(start[0] + end[0]) / 2, end[1]], end];
    } else if (out) {
      pts = [start, [start[0], end[1]], end];
    } else {
      pts = [start, [end[0], start[1]], end];
    }
    const clean = pts.filter((p, i) => i === 0 || Math.abs(p[0] - pts[i - 1][0]) > 0.5
      || Math.abs(p[1] - pts[i - 1][1]) > 0.5);
      const final = clean.length > 1 ? clean : [start, end];
    return { pts: final, mid: this._mid(final) };
  }

  /* the label rides on the longest leg, pushed to the side so the line stays unbroken */
  _mid(pts) {
    let best = 0, bestLen = -1;
    for (let i = 0; i + 1 < pts.length; i++) {
      const len = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
      if (len > bestLen) { bestLen = len; best = i; }
    }
    const [a, b] = [pts[best], pts[best + 1]];
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    return Math.abs(a[0] - b[0]) < 1 ? [mx + 16, my] : [mx, my - 13];
  }

  _edgeGroup(edge, index) {
    const { pts, mid } = this.route(edge);
    if (pts.length < 2) return el("g");
    const on = this.sel?.kind === "edge" && this.sel.id === index;
    const bad = this.flagged && (this.flagged.has(edge.from) || this.flagged.has(edge.to));
    const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" ");
    const g = el("g", { class: `edge${on ? " on" : ""}${bad ? " bad" : ""}`, "data-role": "edge",
                       "data-id": index });
    g.appendChild(el("path", { d, class: "hit", fill: "none" }));
    g.appendChild(el("path", { d, class: "wire", fill: "none", "marker-end": on ? "url(#tip-on)" : "url(#tip)",
                               "vector-effect": "non-scaling-stroke" }));
    const label = edge.label || "";
    const [mx, my] = mid;
    if (label) {
      const width = Math.max(22, measure.measureText(label).width + 12);
      g.appendChild(el("rect", { x: mx - width / 2, y: my - 11, width, height: 18, rx: 4,
                                 class: "label-bg" }));
      g.appendChild(el("text", { x: mx, y: my + 2, class: "label", "text-anchor": "middle",
                                 "data-role": "label", "data-id": index },
        [document.createTextNode(label)]));
    }
    return g;
  }

  /* ------------------------------------------------------------ input */
  _bind() {
    this.svg.addEventListener("pointerdown", (ev) => this._down(ev));
    window.addEventListener("pointermove", (ev) => this._move(ev));
    window.addEventListener("pointerup", (ev) => this._up(ev));
    this.svg.addEventListener("dblclick", (ev) => this._double(ev));
    this.svg.addEventListener("wheel", (ev) => {
      if (!ev.ctrlKey) {                             // a plain wheel scrolls the canvas
        ev.preventDefault();
        this.view.tx -= ev.shiftKey ? ev.deltaY : 0;
        this.view.ty -= ev.shiftKey ? 0 : ev.deltaY;
        this._applyView();
        return;
      }
      ev.preventDefault();
      this.zoomBy(ev.deltaY < 0 ? 1.1 : 0.9, { x: ev.clientX - this.stage.getBoundingClientRect().left,
                                               y: ev.clientY - this.stage.getBoundingClientRect().top });
    }, { passive: false });
    this.altKey = false;
    window.addEventListener("keydown", (ev) => {
      this.altKey = ev.altKey;
      if (ev.key === "Escape") { this._cancel(); this.sel = null; this.render(); }
      if ((ev.key === "Delete" || ev.key === "Backspace") && this.sel && !this.editing) {
        ev.preventDefault();
        this.remove(this.sel.kind === "node" ? this.sel.id : null);
      }
      if (this.sel?.kind === "node" && !this.editing && ev.key.startsWith("Arrow")) {
        ev.preventDefault();
        const node = this.byId(this.sel.id);
        const step = (ev.shiftKey ? GRID * 2 : GRID) * (ev.key === "ArrowRight" || ev.key === "ArrowDown" ? 1 : -1);
        this._push();
        if (ev.key.includes("Left") || ev.key.includes("Right")) node.x += step; else node.y += step;
        this.render();
        this._changed("nudge");
      }
    });
    window.addEventListener("keyup", (ev) => { this.altKey = ev.altKey; });
  }

  _target(ev) {
    let node = ev.target;
    while (node && node !== this.svg) {
      if (node.dataset && node.dataset.role) return node;
      node = node.parentNode;
    }
    return null;
  }

  _down(ev) {
    if (ev.button === 2) return;
    const hit = this._target(ev);
    const role = hit?.dataset.role;
    const world = this.toWorld(ev);
    if (role === "port") {
      this._drag = { mode: "link", from: hit.dataset.id, side: hit.dataset.side, to: null, pts: null };
      return;
    }
    if (role === "size") {
      const node = this.byId(hit.dataset.id);
      this._push();
      this._drag = { mode: "size", id: node.id, dir: hit.dataset.dir, start: world,
                     base: { ...this.sizeOf(node), x: node.x, y: node.y } };
      return;
    }
    if (role === "node") {
      const node = this.byId(hit.dataset.id);
      this.sel = { kind: "node", id: node.id };
      this._drag = { mode: "move", id: node.id, dx: world.x - node.x, dy: world.y - node.y,
                     moved: false };
      this.render();
      return;
    }
    if (role === "note") {
      const note = this.chart.notes[+hit.dataset.id];
      this._push();
      this.sel = { kind: "note", id: +hit.dataset.id };
      this._drag = { mode: "note", i: +hit.dataset.id, dx: world.x - note.x, dy: world.y - note.y };
      this.render();
      return;
    }
    if (role === "edge" || role === "label") {
      this.sel = { kind: "edge", id: +hit.dataset.id };
      this.render();
      return;
    }
    this.sel = null;
    this._drag = { mode: "pan", sx: ev.clientX, sy: ev.clientY, tx: this.view.tx, ty: this.view.ty };
    this.render();
  }

  _move(ev) {
    const drag = this._drag;
    if (!drag) return;
    const world = this.toWorld(ev);
    if (drag.mode === "pan") {
      this.view.tx = drag.tx + (ev.clientX - drag.sx);
      this.view.ty = drag.ty + (ev.clientY - drag.sy);
      this._applyView();
      return;
    }
    if (drag.mode === "move") {
      if (!drag.moved) { this._push(); drag.moved = true; }
      const node = this.byId(drag.id);
      node.x = this.snapTo(world.x - drag.dx);
      node.y = this.snapTo(world.y - drag.dy);
      this.render();
      return;
    }
    if (drag.mode === "note") {
      const note = this.chart.notes[drag.i];
      note.x = this.snapTo(world.x - drag.dx);
      note.y = this.snapTo(world.y - drag.dy);
      this.render();
      return;
    }
    if (drag.mode === "size") {
      const node = this.byId(drag.id);
      const s = drag.base;
      let w = s.w, h = s.h;
      if (drag.dir.includes("e")) w = s.w + (world.x - drag.start.x);
      if (drag.dir.includes("w")) w = s.w - (world.x - drag.start.x);
      if (drag.dir.includes("s")) h = s.h + (world.y - drag.start.y);
      if (drag.dir.includes("n")) h = s.h - (world.y - drag.start.y);
      node.w = Math.max(MIN.w, this.snapTo(w));
      node.h = Math.max(MIN.h, this.snapTo(h));
      this.render();
      return;
    }
    if (drag.mode === "link") {
      const a = this.byId(drag.from);
      const pa = this.ports(a);
      const from = pa[drag.side];
      const over = this._hitNode(ev);
      drag.to = over;
      drag.pts = over ? this.route({ from: drag.from, to: over }).pts : [from, [world.x, world.y]];
      this.lOver.appendChild(el("path", {
        d: (drag.pts.length > 1 ? drag.pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join(" ")
            : `M${from[0]},${from[1]}`) + (drag.pts.length > 1 ? "" : ` L${world.x},${world.y}`),
        class: "wiring", fill: "none", "marker-end": "url(#tip-on)",
        "vector-effect": "non-scaling-stroke" }));
      if (over) {
        const n = this.byId(over);
        this.lOver.appendChild(el("rect", { x: n.x - this.sizeOf(n).w / 2 - 5, y: n.y - this.sizeOf(n).h / 2 - 5,
          width: this.sizeOf(n).w + 10, height: this.sizeOf(n).h + 10, rx: 9, class: "droptarget" }));
      }
      return;
    }
  }

  _up(ev) {
    const drag = this._drag;
    this._drag = null;
    if (!drag) return;
    if (drag.mode === "link") {
      this.render();
      if (drag.to && drag.to !== drag.from) {
        if (!this.connect(drag.from, drag.to)) this._flash("those two blocks are already joined");
        return;
      }
      this._flash("drag the arrow onto another block to join them");
      return;
    }
    if (["move", "size", "note"].includes(drag.mode)) this._changed(drag.mode);
  }

  _hitNode(ev) {
    const world = this.toWorld(ev);
    let best = null, bestD = 1e9;
    for (const n of this.chart.nodes) {
      const s = this.sizeOf(n);
      const d = Math.max(Math.abs(world.x - n.x) - s.w / 2, Math.abs(world.y - n.y) - s.h / 2);
      if (d < 8 && d < bestD) { best = n.id; bestD = d; }
    }
    return best;
  }

  _double(ev) {
    const hit = this._target(ev);
    if (!hit) {
      const world = this.toWorld(ev);
      const node = this._hitNode(ev);
      if (!node) { this._openEditor(null, { x: world.x, y: world.y }); }
      return;
    }
    if (hit.dataset.role === "node") this._openEditor(this.byId(hit.dataset.id));
    if (hit.dataset.role === "note") this._openNoteEditor(+hit.dataset.id);
    if (hit.dataset.role === "edge" || hit.dataset.role === "label") {
      const i = +hit.dataset.id;
      const src = this.byId(this.chart.edges[i].from);
      this._openPrompt(src?.type === "decision" ? "yes / no" : "label (optional)",
                       this.chart.edges[i].label, (v) => this.labelEdge(i, v));
    }
  }

  _cancel() {
    if (this._drag?.mode === "link") { this._drag = null; this.render(); }
  }

  _flash(message) {
    this.dispatchEvent(new CustomEvent("hint", { detail: { message } }));
  }

  /* A floating <input> on top of the shape — quicker than a properties side panel. */
  _openEditor(node, at) {
    if (!node && at) {
      const kind = window.prompt("shape type?", "process");
      if (kind && this.kinds[kind]) this.add(kind, at);
      return;
    }
    const box = this.toScreen({ x: node.x, y: node.y });
    const size = this.sizeOf(node);
    const input = document.createElement("input");
    input.className = "float-in";
    input.value = node.text || "";
    input.placeholder = this.kinds[node.type]?.hint || "text";
    input.style.left = `${Math.max(6, box.x - (size.w * this.view.k) / 2)}px`;
    input.style.top = `${box.y - 14}px`;
    input.style.width = `${Math.max(120, size.w * this.view.k)}px`;
    this.stage.appendChild(input);
    input.focus();
    input.select();
    this.editing = true;
    const done = (keep) => {
      if (!input.isConnected) return;
      const value = input.value.trim();
      input.remove();
      this.editing = false;
      if (keep && value !== node.text) this.update(node.id, { text: value });
      else this.render();
    };
    input.addEventListener("keydown", (ev) => {
      ev.stopPropagation();
      if (ev.key === "Enter") done(true);
      if (ev.key === "Escape") done(false);
      if (ev.key === "Tab") { ev.preventDefault(); done(true); this._nextBlock(node.id); }
    });
    input.addEventListener("blur", () => done(true));
  }

  _openNoteEditor(index) {
    const note = this.chart.notes[index];
    const box = this.toScreen({ x: note.x, y: note.y });
    const input = document.createElement("textarea");
    input.className = "float-in wide";
    input.value = note.text || "";
    input.style.left = `${box.x}px`;
    input.style.top = `${box.y}px`;
    input.style.width = "190px";
    this.stage.appendChild(input);
    input.focus();
    this.editing = true;
    const done = (keep) => {
      if (!input.isConnected) return;
      const value = input.value.trim();
      input.remove();
      this.editing = false;
      if (keep) this.setNoteText(index, value);
    };
    input.addEventListener("keydown", (ev) => {
      ev.stopPropagation();
      if (ev.key === "Enter" && !ev.shiftKey) done(true);
      if (ev.key === "Escape") done(false);
    });
    input.addEventListener("blur", () => done(true));
  }

  _openPrompt(what, value, apply) {
    const answer = window.prompt(what, value || "");
    if (answer !== null) apply(answer.trim());
  }

  _nextBlock(from) {
    const i = this.chart.nodes.findIndex((n) => n.id === from);
    const next = this.chart.nodes[i + 1];
    if (next) { this.sel = { kind: "node", id: next.id }; this.render(); this._openEditor(next); }
  }

  /* quick yes/no for the two arrows of a decision */
  autoLabel(id) {
    const out = this.chart.edges.filter((e) => e.from === id);
    if (out.length !== 2) { this._flash("a decision needs exactly two arrows before they can be labelled"); return; }
    this._push();
    const [a, b] = out;
    const target = (e) => this.byId(e.to);
    const left = target(a).x <= target(b).x ? a : b;
    const right = left === a ? b : a;
    left.label = "yes";
    right.label = "no";
    this.render();
    this._changed("label");
  }

  setFlagged(ids) {
    this.flagged = ids && ids.size ? ids : null;
    this.render();
  }
}

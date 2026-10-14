/* The wiring: palette, panes, and the five HTTP calls the backend offers.
 *
 *   /api/meta            what shapes exist
 *   /api/generate        chart in → Python out (or the list of problems)
 *   /api/run             chart + stdin → what the program printed
 *   /api/tidy            chart in → the same chart, straightened out
 *   /api/import/image    a photo of a hand-drawn chart in → an editable chart out
 */
import { ChartEditor, outlinePath } from "./editor.js";

const stage = document.getElementById("stage");
const palette = document.getElementById("palette");
const extras = document.getElementById("extras");
const codeBox = document.getElementById("code");
const outBox = document.getElementById("out");
const listEl = document.getElementById("plist");
const notesEl = document.getElementById("notes");
const pill = document.getElementById("pill");
const counts = document.getElementById("counts");
const zoomEl = document.getElementById("zoom");
const hint = document.getElementById("hint");
const nameInput = document.getElementById("chartName");
const stdinEl = document.getElementById("stdin");
const picBox = document.getElementById("pic");
const toast = document.getElementById("toast");

const state = { meta: null, editor: null, python: "", marks: [], problems: [], picUrl: null,
                picStale: true, tab: "code", busy: false, savedNote: "" };
let timer = null, picTimer = null;

/* -------------------------------------------------------------------- plumbing */
async function api(path, body, opts = {}) {
  const init = { headers: {}, ...opts };
  if (body !== undefined) {
    init.method = init.method || "POST";             // a body with no method is illegal
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (path === "/api/render" && res.ok) return res.blob();
  const data = await res.json().catch(() => ({ error: "the server did not answer" }));
  if (!res.ok && data && data.problems) return data;
  if (!res.ok) throw new Error((data && (data.error || data.message)) || `HTTP ${res.status}`);
  return data;
}

function say(message, ms = 2600) {
  toast.hidden = false;
  toast.textContent = message;
  clearTimeout(say._t);
  say._t = setTimeout(() => { toast.hidden = true; }, ms);
}

function esc(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

/* ---------------------------------------------------------------------- boot */
boot();

async function boot() {
  try {
    state.meta = await api("/api/meta");
  } catch (err) {
    stage.innerHTML = `<div class="hint">the backend did not answer (${esc(err.message)}) —
      start it with <code>python -m flow2code web</code></div>`;
    return;
  }
  state.editor = new ChartEditor(stage, state.meta);
  window.__f2c_editor = state.editor;      // so the browser console can poke at the chart
  buildPalette();
  buildExtras();
  wire();
  state.editor.addEventListener("change", () => { schedule(); autosave(); });
  state.editor.addEventListener("hint", (ev) => say(ev.detail.message));
  state.editor.addEventListener("viewport", () => { zoomEl.textContent = `${Math.round(state.editor.view.k * 100)}%`; });

  const draft = localStorage.getItem("f2c.draft");
  if (draft) {
    try {
      state.editor.setChart(JSON.parse(draft));
      say("your last chart was restored from this browser");
      refresh();
      return;
    } catch { /* a broken draft just means we start fresh */ }
  }
  const starter = state.meta.examples.find((e) => e.name === "even_odd") || state.meta.examples[0];
  if (starter) await loadExample(starter.name); else newChart();
}

function buildPalette() {
  const byGroup = {};
  for (const kind of state.meta.kinds) (byGroup[kind.group] ||= []).push(kind);
  palette.innerHTML = "";
  for (const group of state.meta.groups) {
    const head = document.createElement("div");
    head.className = "rail-h";
    head.textContent = ({ terminals: "Terminators", data: "Input / output", process: "Process & decision",
      documents: "Documents & storage", links: "Connectors" })[group] || group;
    palette.appendChild(head);
    const wrapEl = document.createElement("div");
    wrapEl.className = "rail-group";
    for (const kind of byGroup[group] || []) wrapEl.appendChild(chipFor(kind));
    palette.appendChild(wrapEl);
  }
}

function chipFor(kind) {
  const btn = document.createElement("button");
  btn.className = "chip";
  btn.draggable = true;
  btn.dataset.kind = kind.type;
  btn.title = `${kind.label} — ${kind.hint}`;
  const scale = Math.min(34 / (kind.w + 8), 22 / (kind.h + 6));
  const w = kind.w * scale + 8, h = kind.h * scale + 8;
  btn.innerHTML = `<svg viewBox="${-w / 2} ${-h / 2} ${w} ${h}" aria-hidden="true">
      <path d="${outlinePath(kind.shape, kind.w * scale, kind.h * scale)}"/></svg>
    <span class="t"><b>${esc(kind.label)}</b><span>${esc(kind.hint)}</span></span>`;
  btn.addEventListener("click", () => place(kind.type));
  btn.addEventListener("dragstart", (ev) => {
    ev.dataTransfer.setData("text/x-f2c-kind", kind.type);
    ev.dataTransfer.effectAllowed = "copy";
  });
  return btn;
}

function buildExtras() {
  const note = document.createElement("button");
  note.className = "chip note";
  note.innerHTML = `<svg viewBox="-20 -14 40 28" aria-hidden="true">
      <path d="M-16,-11 H16 V6 L9,11 H-16 Z"/></svg>
    <span class="t"><b>Note</b><span>comment on the drawing</span></span>`;
  note.addEventListener("click", () => {
    state.editor.addNote(centre());
    say("notes stay on the drawing — they never become code");
  });
  extras.appendChild(note);
}

/* ------------------------------------------------------------------- actions */
function centre() {
  const box = stage.getBoundingClientRect();
  return state.editor.toWorld({ clientX: box.left + box.width / 2,
                                clientY: box.top + box.height / 2 + (Math.random() * 40 - 20) });
}

function place(kind) {
  const node = state.editor.add(kind, snapCentre(centre()));
  say(`${kind} block added — double-click it to type`);
  return node;
}

function snapCentre(point) {
  return { x: state.editor.snapTo(point.x), y: state.editor.snapTo(point.y) };
}

async function refresh() {
  const chart = state.editor.getChart();
  if (!chart.nodes.length) { paintEmpty(); return; }
  const answer = await api("/api/generate", { chart }).catch((err) => {
    paintError(err.message); return null;
  });
  if (!answer) return;
  state.python = answer.python || "";
  state.marks = answer.marks || [];
  state.problems = answer.problems || [];
  state.picStale = true;
  paintPill(answer);
  paintCode(answer);
  paintProblems(answer);
  if (!document.activeElement || document.activeElement !== stdinEl) stdinEl.value = answer.stdin || "";
  clearTimeout(picTimer);
  picTimer = setTimeout(() => { if (state.tab === "pic") showPicture(); }, 400);
}

function schedule() {
  clearTimeout(timer);
  timer = setTimeout(refresh, 300);
}

function paintEmpty() {
  state.python = ""; state.marks = []; state.problems = [];
  codeBox.innerHTML = `<p class="quiet">Nothing to generate yet. Drag a <b>Start</b> block out,
    or open an example.</p>`;
  listEl.innerHTML = "";
  pill.className = "pill";
  pill.textContent = "empty chart";
  counts.textContent = "0 blocks · 0 arrows";
  picBox.innerHTML = `<p class="quiet">Add a block and the picture appears here.</p>`;
  state.picStale = true;
}

function paintError(message) {
  codeBox.innerHTML = `<p class="quiet">the server said: ${esc(message)}</p>`;
  pill.className = "pill bad";
  pill.textContent = "the server refused this chart";
}

function paintPill(answer) {
  counts.textContent = `${answer.blocks || 0} blocks · ${answer.arrows || 0} arrows`
    + (answer.line_count ? ` · ${answer.line_count} lines of Python` : "");
  hint.hidden = (answer.blocks || 0) > 0;
  if (answer.ok) {
    pill.className = "pill ok";
    pill.textContent = `valid · ${answer.line_count} lines ready`;
  } else {
    pill.className = "pill bad";
    pill.textContent = `${answer.problems.length} problem${answer.problems.length > 1 ? "s" : ""}`;
  }
}

/* ------------------------------------------------------------------ code pane */
const TOKEN = /(&quot;.*?&quot;|&#39;.*?&#39;|".*?"|'.*?')|(#[^<]*)|(\b(?:if|elif|else|while|for|in|not|and|or|True|False|None|return|def)\b)/;

function highlight(line) {
  let rest = esc(line), out = "";
  for (;;) {
    const m = rest.match(TOKEN);
    if (!m) { out += rest; return out; }
    out += rest.slice(0, m.index);
    const cls = m[1] ? "str" : m[2] ? "cmt" : "kw";
    out += `<span class="${cls}">${m[0]}</span>`;
    rest = rest.slice(m.index + m[0].length);
  }
}

function paintCode(answer) {
  if (!answer.python) {
    codeBox.innerHTML = `<p class="quiet">${answer.note ? esc(answer.note)
      : "fix the problems in the chart and the code appears here"}</p>`;
    document.getElementById("codeNote").textContent = "nothing generated yet";
    return;
  }
  document.getElementById("codeNote").textContent =
    `${answer.line_count} lines · each one traced back to its block`;
  const rows = answer.python.split("\n").map((line, i) => {
    const src = (answer.marks || [])[i];
    const cls = !line.trim() ? "ln blank" : "ln";
    return `<div class="${cls}"><span class="no">${i + 1}</span>`
      + `<span class="src" data-goto="${esc(src || "")}">${src ? esc(src) : ""}</span>`
      + `<code>${highlight(line)}</code></div>`;
  });
  codeBox.innerHTML = rows.join("");
  codeBox.querySelectorAll(".src").forEach((sp) => {
    sp.addEventListener("click", () => {
      const id = sp.dataset.goto;
      if (!id) return;
      state.editor.sel = { kind: "node", id };
      state.editor.render();
      state.editor.centreOn(id);
    });
  });
}

function paintProblems(answer) {
  const items = answer.problems || [];
  notesEl.innerHTML = (answer.notes || []).map((n) => `<div>${esc(n)}</div>`).join("");
  document.getElementById("pcnt").textContent = items.length ? items.length : "";
  if (!items.length) {
    listEl.innerHTML = `<li class="good" style="border-left-color:var(--ok)">
      the checker walked this chart and found nothing to complain about — one Start, every
      block reachable, both branches of every decision, no dangling arrows.</li>`;
    state.editor.setFlagged(new Set());
    return;
  }
  state.editor.setFlagged(new Set(items.flatMap((p) => p.ids)));
  listEl.innerHTML = items.map((p) => `<li>
      ${esc(p.message)}
      ${p.ids.length ? `<span class="go">${p.ids.map((id) => `<button data-jump="${esc(id)}">${esc(id)}</button>`).join("")}</span>` : ""}
    </li>`).join("");
  listEl.querySelectorAll("[data-jump]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.jump;
      state.editor.sel = { kind: "node", id };
      state.editor.render();
      state.editor.centreOn(id);
    });
  });
}

/* ------------------------------------------------------------------- run pane */
async function runIt() {
  if (state.busy) return;
  state.busy = true;
  const btn = document.getElementById("runBtn");
  btn.disabled = true;
  btn.textContent = "running…";
  outBox.innerHTML = `<span class="quiet">running in a separate python process…</span>`;
  const chart = state.editor.getChart();
  let answer;
  try {
    answer = await api("/api/run", { chart, stdin: stdinEl.value });
  } catch (err) {
    outBox.innerHTML = `<span class="err">${esc(err.message)}</span>`;
    finish();
    return;
  }
  if (!answer.ran) {
    paintProblems(answer);
    paintCode(answer);
    paintPill(answer);
    outBox.innerHTML = `<span class="err">${esc(answer.note || "the chart does not generate yet")}</span>`;
    if (state.tab !== "problems") showTab("problems");
    finish();
    return;
  }
  const bits = [];
  if (answer.stdout) bits.push(esc(answer.stdout.replace(/\n$/, "")));
  if (answer.stderr) bits.push(`<span class="err">${esc(answer.stderr)}</span>`);
  if (!bits.length) bits.push(`<span class="quiet">(the program printed nothing)</span>`);
  bits.push(`<span class="meta">— exit ${answer.exit} in ${answer.ms} ms${answer.note ? ` · ${esc(answer.note)}` : ""}</span>`);
  outBox.innerHTML = bits.join("\n");
  showTab("run");
  finish();
}

function finish() {
  state.busy = false;
  const btn = document.getElementById("runBtn");
  btn.disabled = false;
  btn.textContent = "Run ▸";
}

/* ---------------------------------------------------------------- picture pane */
async function showPicture(force) {
  if (!state.picStale && !force) return;
  if (!state.editor.chart.nodes.length) {
    picBox.innerHTML = `<p class="quiet">Add a block and the picture appears here.</p>`;
    return;
  }
  try {
    const res = await fetch("/api/render", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chart: state.editor.getChart() }) });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new Error(data?.problems?.[0]?.message || `the server answered ${res.status}`);
    }
    const blob = await res.blob();
    if (state.picUrl) URL.revokeObjectURL(state.picUrl);
    state.picUrl = URL.createObjectURL(blob);
    picBox.innerHTML = `<img src="${state.picUrl}" alt="the flowchart, rendered by the server">`;
    state.picStale = false;
  } catch (err) {
    picBox.innerHTML = `<p class="quiet">${esc(err.message)}</p>`;
  }
}

/* ----------------------------------------------------------------- file doors */
function newChart() {
  state.editor.setChart({
    name: "untitled",
    nodes: [
      { id: "s1", type: "start", text: "Start", x: 380, y: 80 },
      { id: "e1", type: "end", text: "End", x: 380, y: 200 },
    ],
    edges: [],
    notes: [],
  });
  localStorage.removeItem("f2c.draft");
  nameInput.value = "untitled";
  refresh();
}

function download(name, text, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function saveChart() {
  const chart = state.editor.getChart();
  const name = (chart.name || "chart").replace(/[^A-Za-z0-9._-]+/g, "_");
  download(`${name}.flow.json`, JSON.stringify(chart, null, 2) + "\n", "application/json");
  say(`downloaded ${name}.flow.json — Open… reads it back`);
}

function saveToServer() {
  api("/api/save", { chart: state.editor.getChart() }).then((answer) => {
    if (answer.ok) say(`saved on the server: ${answer.path}`);
    else say(answer.problems?.[0]?.message || "the server refused that");
  });
}

async function loadExample(name) {
  const chart = await api(`/api/examples/${name}`);
  state.editor.setChart(chart);
  nameInput.value = chart.name || name;
  showTab("code");
  await refresh();
}

function openFileInput() { document.getElementById("fileOpen").click(); }

async function importImage(file) {
  if (!file) return;
  say(`reading ${file.name}…`, 8000);
  const form = new FormData();
  form.append("file", file);
  let answer;
  try {
    const res = await fetch("/api/import/image", { method: "POST", body: form });
    answer = await res.json();
  } catch (err) {
    say(`the upload failed: ${err.message}`);
    return;
  }
  if (answer.source_image) {
    document.getElementById("imported").hidden = false;
    document.getElementById("importedImg").src = answer.source_image;
  }
  if (!answer.chart) {
    showTab("problems");
    paintProblems(answer);
    say(answer.problems?.[0]?.message || "nothing could be read from that picture");
    return;
  }
  state.editor.setChart(answer.chart);
  nameInput.value = "imported chart";
  state.python = answer.python || "";
  state.marks = answer.marks || [];
  paintCode(answer);
  paintProblems(answer);
  paintPill(answer);
  showTab("problems");
  say(`found ${answer.blocks} blocks and ${answer.arrows} arrows — check the arrows, then fix the words`);
}

function autosave() {
  clearTimeout(autosave._t);
  autosave._t = setTimeout(() => {
    localStorage.setItem("f2c.draft", JSON.stringify(state.editor.getChart()));
    document.getElementById("saved").textContent = `draft kept in this browser · ${new Date().toLocaleTimeString()}`;
  }, 500);
}

/* ----------------------------------------------------------------- wiring up */
function showTab(which) {
  state.tab = which;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === which));
  document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p.id === `pane-${which}`));
  if (which === "pic") showPicture();
}

function wire() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));

  document.querySelectorAll("[data-act]").forEach((btn) => {
    btn.addEventListener("click", () => act(btn.dataset.act));
  });

  stdinEl.addEventListener("input", () => {
    state.editor.setStdin(stdinEl.value);
    schedule();
  });

  nameInput.addEventListener("input", () => {
    state.editor.setName(nameInput.value);
  });

  stage.addEventListener("dragover", (ev) => {
    if (ev.dataTransfer.types.includes("Files")) {
      ev.preventDefault();
      document.getElementById("drop").hidden = false;
    }
  });
  stage.addEventListener("dragleave", () => { document.getElementById("drop").hidden = true; });
  stage.addEventListener("drop", (ev) => {
    document.getElementById("drop").hidden = true;
    const kind = ev.dataTransfer.getData("text/x-f2c-kind");
    if (kind) {
      ev.preventDefault();
      const world = state.editor.toWorld(ev);
      state.editor.add(kind, { x: state.editor.snapTo(world.x), y: state.editor.snapTo(world.y) });
      return;
    }
    const file = ev.dataTransfer.files && ev.dataTransfer.files[0];
    if (file) {
      ev.preventDefault();
      importImage(file);
    }
  });

  document.getElementById("fileImage").addEventListener("change", (ev) => {
    importImage(ev.target.files[0]);
    ev.target.value = "";
  });
  document.getElementById("fileOpen").addEventListener("change", (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    file.text().then((text) => {
      try {
        const chart = JSON.parse(text);
        state.editor.setChart(chart);
        nameInput.value = chart.name || file.name.replace(/\.json$/, "");
        refresh();
        say(`read ${file.name}`);
      } catch (err) {
        say(`that file is not a chart (${err.message})`);
      }
    });
    ev.target.value = "";
  });

  document.getElementById("examples").addEventListener("click", (ev) => {
    if (ev.target === ev.currentTarget || ev.target.hasAttribute("data-close")) {
      ev.currentTarget.hidden = true;
    }
  });

  window.addEventListener("keydown", (ev) => {
    const typing = /INPUT|TEXTAREA/.test(document.activeElement?.tagName || "");
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z" && !typing) {
      ev.preventDefault();
      if (!(ev.shiftKey ? state.editor.redo() : state.editor.undo())) say("nothing left to undo");
      schedule();
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s") {
      ev.preventDefault();
      saveChart();
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
      ev.preventDefault();
      runIt();
    } else if (ev.key === "Escape") {
      document.getElementById("examples").hidden = true;
    }
  });

  document.body.addEventListener("dragover", (ev) => { if (ev.dataTransfer.types.includes("Files")) ev.preventDefault(); });
  document.body.addEventListener("drop", (ev) => {
    if (ev.target.closest("#stage")) return;
    const file = ev.dataTransfer.files?.[0];
    if (file && /^image\//.test(file.type)) { ev.preventDefault(); importImage(file); }
  });
}

function act(name) {
  const editor = state.editor;
  switch (name) {
    case "new": newChart(); break;
    case "open": openFileInput(); break;
    case "save": saveChart(); break;
    case "save-server": saveToServer(); break;
    case "examples": showExamples(); break;
    case "upload": document.getElementById("fileImage").click(); break;
    case "undo": editor.undo() || say("nothing left to undo"); schedule(); break;
    case "redo": editor.redo() || say("nothing to redo"); schedule(); break;
    case "fit": editor.fit(); break;
    case "zoomIn": editor.zoomBy(1.18); break;
    case "zoomOut": editor.zoomBy(1 / 1.18); break;
    case "snap": {
      editor.snap = !editor.snap;
      const btn = document.getElementById("snapBtn");
      btn.setAttribute("aria-pressed", String(editor.snap));
      say(editor.snap ? "snapping to a 10 px grid" : "free placement");
      break;
    }
    case "auto":
      api("/api/tidy", { chart: editor.getChart() }).then((answer) => {
        if (!answer.ok) { say(answer.problems?.[0]?.message || "could not tidy that"); return; }
        editor.replace(answer.chart);
        editor.fit();
        say("straightened: one row per level, read top to bottom");
      });
      break;
    case "copy":
      if (!state.python) { say("there is no code to copy yet"); break; }
      navigator.clipboard.writeText(state.python).then(() => say("Python copied"),
        () => say("the browser refused the clipboard"));
      break;
    case "dlpy":
      if (!state.python) { say("there is no code to save yet"); break; }
      download(`${(nameInput.value || "chart").replace(/[^A-Za-z0-9._-]+/g, "_")}.py`,
        `${state.python}\n`, "text/x-python");
      break;
    case "dlpng":
      if (state.picUrl) {
        const a = document.createElement("a");
        a.href = state.picUrl;
        a.download = `${(nameInput.value || "chart").replace(/[^A-Za-z0-9._-]+/g, "_")}.png`;
        a.click();
      } else { showPicture(true); say("here it comes…"); }
      break;
    case "run": runIt(); break;
    default: break;
  }
}

function showExamples() {
  const sheet = document.getElementById("examples");
  const list = document.getElementById("exList");
  list.innerHTML = "";
  for (const ex of state.meta.examples) {
    const row = document.createElement("button");
    row.className = `ex${ex.broken ? " brk" : ""}`;
    row.innerHTML = `<b>${esc(ex.label)}</b>
      <span class="m">${esc(ex.note || "no note")}
        ${ex.problems && ex.problems.length ? `· the checker says: ${esc(ex.problems[0].message)}` : ""}</span>
      <span class="b">${ex.broken ? "broken on purpose" : `${ex.blocks} blocks · ${ex.arrows} arrows`}</span>`;
    row.addEventListener("click", () => {
      sheet.hidden = true;
      loadExample(ex.name);
    });
    list.appendChild(row);
  }
  const foot = document.createElement("div");
  foot.className = "quiet";
  foot.style.padding = "8px 12px";
  foot.innerHTML = `These are the files in <code>samples/</code> — the same charts the command line
    reads. <button class="lnk" data-act="save-server">Save the chart you drew into samples/</button>
    and it shows up here after a refresh.`;
  list.appendChild(foot);
  foot.querySelector("[data-act]").addEventListener("click", saveToServer);
  sheet.hidden = false;
}

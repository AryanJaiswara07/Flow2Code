/* The pointer-level test: drag a block, pull an arrow from its port handle, resize, type
 * into a shape, label a decision, delete an arrow.  Same fake browser as smoke.mjs. */
import path from "node:path";
import { openEditor, makeChecks } from "./browser.mjs";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const BASE = process.env.F2C || "http://127.0.0.1:8000";
const { window, wait } = await openEditor(BASE);
await import(path.resolve(HERE, "..", "..", "flow2code", "web", "app.js"));
await wait(1300);
window.localStorage.removeItem("f2c.draft");

const ed = window.__f2c_editor;
const { check, done } = makeChecks("interaction");
if (!ed) { console.log("no editor handle"); process.exit(1); }

const nodeAt = (id) => window.document.querySelector(`.node[data-id="${id}"]`);
const world = (id) => { const n = ed.byId(id); return { x: n.x, y: n.y }; };
const edges = () => ed.chart.edges.length;
function fire(type, x, y, target) {
  (target || window).dispatchEvent(new window.MouseEvent(type,
    { clientX: x, clientY: y, bubbles: true, cancelable: true, button: 0 }));
}
function drag(from, to, on) {
  fire("pointerdown", from.x, from.y, on);
  fire("pointermove", (from.x + to.x) / 2, (from.y + to.y) / 2, window);
  fire("pointermove", to.x, to.y, window);
  fire("pointerup", to.x, to.y, window);
}
const screen = (w) => ed.toScreen(w);

console.log("\n dragging a block");
ed.sel = { kind: "node", id: "n2" };
ed.render();
const was = { ...world("n2") };
drag(screen(was), { x: screen(was).x + 40, y: screen(was).y + 25 }, nodeAt("n2"));
const now = world("n2");
check("the block followed the pointer",
  Math.abs(now.x - was.x - 40) < 6 && Math.abs(now.y - was.y - 25) < 6,
  `moved ${(now.x - was.x).toFixed(1)}, ${(now.y - was.y).toFixed(1)}`);
check("snapping kept it on the 10 px grid", now.x % 10 === 0 && now.y % 10 === 0, `${now.x},${now.y}`);
ed.snap = false;
drag(screen(now), { x: screen(now).x + 7, y: screen(now).y + 3 }, nodeAt("n2"));
check("with snapping off it moves freely", world("n2").x % 10 !== 0, world("n2").x);
ed.snap = true;
ed.undo();                                           // the free move
check("one undo undid the free move", Math.abs(world("n2").x - (was.x + 40)) < 0.5, world("n2").x);
ed.undo();                                           // the snapped move
await wait(400);
check("two undos are back where it started", Math.abs(world("n2").x - was.x) < 0.5, world("n2").x);

console.log("\n connecting with the port handle");
ed.add("process", { x: was.x + 260, y: was.y + 30 });
ed.render();
const added = ed.chart.nodes[ed.chart.nodes.length - 1].id;
const beforeEdges = edges();
ed.sel = { kind: "node", id: "n2" };
ed.render();
check("a selected block shows four ports", window.document.querySelectorAll(".port").length === 4);
const port = window.document.querySelector('.port[data-id="n2"][data-side="right"]');
const from = screen({ x: +port.getAttribute("cx"), y: +port.getAttribute("cy") });
drag(from, screen(world(added)), port);
check("an arrow appeared", edges() === beforeEdges + 1, `${beforeEdges} → ${edges()}`);
check("it joins the block the pointer was let go on",
  ed.chart.edges.some((e) => e.from === "n2" && e.to === added));
check("no rubber-band line was left behind", !window.document.querySelector(".wiring"));
function text2(sel) {
  return (window.document.querySelector(sel)?.textContent || "").replace(/\s+/g, " ").trim();
}
await wait(700);                                     // the debounce and the round trip
check("and the server counted the new arrow", text2("#counts").includes(`${edges()} arrows`),
  text2("#counts"));

console.log("\n resizing");
const n = ed.byId(added);
const size = { w: ed.sizeOf(n).w, h: ed.sizeOf(n).h };
ed.sel = { kind: "node", id: added };
ed.render();
const grip = window.document.querySelector(`.sz[data-id="${added}"][data-dir="se"]`);
const gripAt = screen({ x: n.x + size.w / 2, y: n.y + size.h / 2 });
drag(gripAt, { x: gripAt.x + 60, y: gripAt.y + 30 }, grip);
const after = ed.sizeOf(ed.byId(added));
check("the box grew", after.w > size.w + 30 && after.h > size.h + 15,
  `${size.w}x${size.h} → ${after.w}x${after.h}`);
check("the chart file remembered the size",
  Math.round(ed.getChart().nodes.find((x) => x.id === added).w) === Math.round(after.w));
const small = window.document.querySelector(`.sz[data-id="${added}"][data-dir="nw"]`);
const smallAt = screen({ x: ed.byId(added).x - after.w / 2, y: ed.byId(added).y - after.h / 2 });
drag(smallAt, { x: smallAt.x + 400, y: smallAt.y + 400 }, small);   // squash it from the corner
check("but never below the minimum", ed.sizeOf(ed.byId(added)).w >= 90, ed.sizeOf(ed.byId(added)).w);

console.log("\n typing into a shape, on a fresh copy of the example");
ed.setChart(await (await fetch(`${BASE}/api/examples/even_odd`)).json());
await wait(700);
check("even_odd came back valid",
  text2("#pill").startsWith("valid"), text2("#pill"));
nodeAt("n4").dispatchEvent(new window.MouseEvent("dblclick", { bubbles: true, cancelable: true,
  clientX: screen(world("n4")).x, clientY: screen(world("n4")).y }));
const input = window.document.querySelector(".float-in");
check("double-click opened a text box over the shape", !!input);
if (input) {
  input.value = 'Print "even number"';
  input.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  await wait(700);
  check("the block took the words", ed.byId("n4").text === 'Print "even number"', ed.byId("n4").text);
  check("the board shows them",
    window.document.querySelector('.node[data-id="n4"] text').textContent.includes("even number"));
  check("and so does the Python", text2("#code").includes('print("even number")'),
    text2("#code").slice(0, 120));
}

console.log("\n a decision's two arrows");
ed.chart.nodes.push({ id: "dd", type: "decision", text: "x > 0?", x: 100, y: 500 });
ed.chart.nodes.push({ id: "yy", type: "output", text: 'Print "yes"', x: -60, y: 620 });
ed.chart.nodes.push({ id: "nn", type: "output", text: 'Print "no"', x: 260, y: 620 });
ed.connect("dd", "yy");
ed.connect("dd", "nn");
ed.render();
const labels = ed.chart.edges.filter((e) => e.from === "dd").map((e) => e.label).sort();
check("the two arrows were labelled for us", labels.join(",") === "no,yes", labels.join("/"));
{
  const painted = [...window.document.querySelectorAll(".edge .label")].map((t) => t.textContent);
  check("the labels are painted beside the lines", painted.includes("yes") && painted.includes("no"),
    painted.join(","));
}
check("the left branch took the yes", ed.chart.edges.find((e) => e.to === "yy").label === "yes");
ed.sel = { kind: "edge", id: ed.chart.edges.findIndex((e) => e.from === "dd" && e.to === "nn") };
window.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Delete", bubbles: true }));
await wait(750);
check("an arrow can be deleted", !ed.chart.edges.some((e) => e.from === "dd" && e.to === "nn"));
check("and the checker noticed the missing branch", text2("#pill").includes("problem"), text2("#pill"));

process.exit(done());

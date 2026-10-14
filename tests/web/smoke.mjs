/* Start the editor in a fake browser and drive it.  This is not a pixel test — jsdom has
 * no layout — but it does prove the wiring: the palette builds, every click reaches the
 * backend, the code and problems panes fill in, undo/tidy/tabs/run all work, and nothing
 * throws on the way.
 *
 *   python -m flow2code web --port 8000 &      # the app, under test
 *   cd tests/web && npm install jsdom && node smoke.mjs
 */
import path from "node:path";
import { openEditor, makeChecks } from "./browser.mjs";

const HERE = path.dirname(new URL(import.meta.url).pathname);
const BASE = process.env.F2C || "http://127.0.0.1:8000";
const { window, errors, wait } = await openEditor(BASE);
await import(path.resolve(HERE, "..", "..", "flow2code", "web", "app.js"));
await wait(1400);                                       // boot() + the first round trip

const { check, done } = makeChecks("smoke");
const $ = (s) => window.document.querySelector(s);
const text = (s) => ($((s))?.textContent || "").replace(/\s+/g, " ").trim();

console.log("\n start-up");
check("the page and its files exist", (await (await fetch(`${BASE}/editor.js`)).ok)
  && (await (await fetch(`${BASE}/styles.css`)).ok));
check("13 shape chips plus the note", window.document.querySelectorAll(".chip").length === 14,
  `${window.document.querySelectorAll(".chip").length}`);
check("every chip draws a symbol", window.document.querySelectorAll(".chip svg path").length === 14);
check("the example chart was opened", text("#counts") === "6 blocks · 6 arrows · 8 lines of Python",
  text("#counts"));
check("the checker is happy", text("#pill").startsWith("valid"), text("#pill"));
check("python is on screen", text("#code").includes("if n % 2 == 0:"));
check("every line is numbered", window.document.querySelectorAll("#code .ln").length === 8,
  `${window.document.querySelectorAll("#code .ln").length} rows`);
{
  const marks = [...window.document.querySelectorAll("#code .src")].filter((x) => x.textContent);
  check("generated lines carry their block id", marks.length >= 4, `${marks.length} marks`);
  marks[2]?.click();
  check("clicking one selects that block on the canvas",
    window.document.querySelectorAll(".node.on").length === 1,
    `${window.document.querySelectorAll(".node.on").length} selected`);
}
check("the run box was filled from the chart", $("#stdin").value.trim().length > 0,
  JSON.stringify($("#stdin").value));
check("problems pane says all clear", text("#plist").includes("found nothing to complain"));

console.log("\n drawing");
const before = window.document.querySelectorAll(".node").length;
window.document.querySelector('.chip[data-kind="process"]').click();
await wait(700);
check("clicking a shape puts it on the canvas",
  window.document.querySelectorAll(".node").length === before + 1);
check("an orphan block stops generation, and says why",
  text("#code").includes("nothing was generated"), text("#code").slice(0, 120));
check("the pill turned unhappy", text("#pill").includes("problem"), text("#pill"));
check("the checker named the orphan", text("#plist").includes("cannot be reached")
  || text("#plist").includes("no path to an End"), text("#plist").slice(0, 160));
const jump = window.document.querySelector("[data-jump]");
check("a problem offers a block to jump to", !!jump);
jump?.click();
await wait(80);
check("jumping selects that block", window.document.querySelectorAll(".node.on").length === 1);

console.log("\n undo, tidy, snap, tabs");
window.document.querySelector('[data-act="undo"]').click();
await wait(500);
check("undo took the block away", window.document.querySelectorAll(".node").length === before);
check("and the chart is valid again", text("#pill").startsWith("valid"), text("#pill"));
window.document.querySelector('[data-act="auto"]').click();
await wait(800);
check("tidy kept the same program", text("#code").includes('print("Even")'));
window.document.querySelector('[data-tab="pic"]').click();
await wait(900);
check("the picture tab shows the server's PNG", !!$("#pic img"), $("#pic").innerHTML.slice(0, 60));
window.document.querySelector('[data-tab="run"]').click();
await wait(60);
check("the run tab is showing", $("#pane-run").className.includes("on"));

console.log("\n running it");
$("#stdin").value = "7\n";
$("#stdin").dispatchEvent(new window.Event("input", { bubbles: true }));
await wait(450);
window.document.querySelector('[data-act="run"]').click();
await wait(1800);
check("the program printed", text("#out").includes("Odd"), text("#out").slice(0, 160));
check("and exited cleanly", text("#out").includes("exit 0"), text("#out").slice(0, 160));

console.log("\n an impossible chart");
const editor = window.__f2c_editor;
const chart = editor.getChart();
chart.nodes.push({ id: "z9", type: "process", text: "", x: 100, y: 100 });
editor.setChart(chart);
await wait(700);
check("an empty block is refused", text("#pill").includes("problem"), text("#pill"));
check("and no code is shown", !text("#code").includes("if n % 2"), text("#code").slice(0, 90));

console.log("\n the examples sheet");
window.document.querySelector('[data-act="examples"]').click();
await wait(80);
const rows = window.document.querySelectorAll("#exList .ex");
check("every sample is listed", rows.length === 8, `${rows.length} rows`);
check("the deliberately broken ones are marked", [...rows].some((r) => r.className.includes("brk")));
[...rows].find((r) => r.textContent.toLowerCase().includes("sum")).click();
await wait(1000);
check("opening one changed the chart", text("#counts").includes("9 blocks"), text("#counts"));
check("the loop became a while", text("#code").includes("while i <= n:"), text("#code").slice(0, 120));
check("its input was remembered", $("#stdin").value.includes("5"), $("#stdin").value);

const draft = window.localStorage.getItem("f2c.draft");
check("the draft is kept in this browser", draft && JSON.parse(draft).nodes.length === 9,
  draft ? `${JSON.parse(draft).nodes.length} nodes` : "none");
check("nothing threw in the page", errors.length === 0, errors.join(" | "));

process.exit(done());

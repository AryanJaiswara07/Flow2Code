import path from "node:path";
import http from "node:http";
import { JSDOM } from "jsdom";

/* A fetch made of node:http.  Node's own client has been observed tripping over the
 * Werkzeug dev server closing a keep-alive socket between two calls, which throws inside
 * undici where no test can catch it; one request per connection, no parser games. */
function request(url, init = {}) {
  const u = new URL(url);
  const body = init.body === undefined ? null : String(init.body);
  return new Promise((resolve, reject) => {
    const req = http.request({
      hostname: u.hostname, port: u.port || 80, path: `${u.pathname}${u.search}`,
      method: init.method || (body !== null ? "POST" : "GET"),
      headers: { Connection: "close", ...(init.headers || {}) },
    }, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const raw = Buffer.concat(chunks);
        resolve({
          ok: res.statusCode >= 200 && res.statusCode < 300,
          status: res.statusCode,
          headers: { get: (k) => res.headers[k.toLowerCase()] || null },
          text: async () => raw.toString("utf8"),
          json: async () => JSON.parse(raw.toString("utf8")),
          blob: async () => new Blob([new Uint8Array(raw)]),
        });
      });
    });
    req.on("error", reject);
    if (body !== null) req.write(body);
    req.end();
  });
}

/* A browser without a screen: the real index.html, the real modules, a stubbed layout.
 * Shared by smoke.mjs and interact.mjs. */
export async function openEditor(base, { width = 800, height = 600 } = {}) {
  const dom = new JSDOM(await (await fetch(`${base}/`)).text(),
    { url: `${base}/`, pretendToBeVisual: true });
  const { window } = dom;
  globalThis.window = window;
  globalThis.document = window.document;
  globalThis.navigator = window.navigator;
  globalThis.localStorage = window.localStorage;
  globalThis.CustomEvent = window.CustomEvent;
  globalThis.Event = window.Event;
  globalThis.EventTarget = window.EventTarget;
  globalThis.MouseEvent = window.MouseEvent;
  globalThis.KeyboardEvent = window.KeyboardEvent;
  globalThis.Blob = window.Blob;
  globalThis.FormData = window.FormData;
  globalThis.getComputedStyle = window.getComputedStyle.bind(window);
  globalThis.fetch = (u, o) => {
    if (o && o.body instanceof window.FormData) {
      return Promise.reject(new Error("the fake browser cannot post a form; the upload route "
        + "is covered by tests/test_webapp.py"));
    }
    return request(String(u).startsWith("http") ? u : base + u, o);
  };
  window.fetch = globalThis.fetch;
  window.URL.createObjectURL = () => "blob:stub";
  window.URL.revokeObjectURL = () => {};
  globalThis.URL.createObjectURL = window.URL.createObjectURL;
  globalThis.URL.revokeObjectURL = window.URL.revokeObjectURL;
  // jsdom has no canvas and no layout: text measuring and the stage box are the two things
  // the editor asks the page for
  window.HTMLCanvasElement.prototype.getContext = () => ({
    font: "", measureText: (t) => ({ width: String(t).length * 7 }) });
  const rect = { left: 0, top: 0, right: width, bottom: height, width, height, x: 0, y: 0 };
  const stage = window.document.getElementById("stage");
  stage.getBoundingClientRect = () => rect;
  const errors = [];
  window.addEventListener("error", (e) => errors.push(String(e.error || e.message)));
  return { dom, window, errors, wait: (ms) => new Promise((r) => setTimeout(r, ms)) };
}

export function makeChecks(label) {
  let pass = 0, fail = 0;
  const check = (name, ok, extra = "") => {
    if (ok) { pass += 1; console.log(`  ok   ${name}`); }
    else { fail += 1; console.log(`  FAIL ${name}${extra ? `  →  ${String(extra).slice(0, 200)}` : ""}`); }
  };
  const done = () => {
    console.log(`\n ${pass} ${label} checks passed, ${fail} failed\n`);
    return fail;
  };
  return { check, done };
}

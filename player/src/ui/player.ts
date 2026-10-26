/** The reel's page: code, visuals, variables and a timeline, wired to a decoded trace. */

import { stateAt, type State } from "../core/trace";
import { composeScene } from "../render/compose";
import { ARROW_DEFS, esc, itemInner, round, type Item, type Scene } from "../render/scene";
import { formatValue } from "../view/format";
import { inferViews } from "../view/infer";
import { actionForKey, endNote, firstSteps, printedBy, STOPS, stepFromHash, type TraceFile } from "./model";
import { STYLES } from "./styles";

export interface MountOptions {
  /** Show the "made with RunReel" link (on by default). */
  mark?: boolean;
}

export interface Player {
  show(n: number): void;
  readonly step: number;
}

const SPEEDS = [0.5, 1, 2, 4, 8];
const BASE_STEPS_PER_SECOND = 2;

export function mount(root: HTMLElement, trace: TraceFile, options: MountOptions = {}): Player {
  const doc = root.ownerDocument;
  if (!doc.getElementById("rr-styles")) {
    const style = doc.createElement("style");
    style.id = "rr-styles";
    style.textContent = STYLES;
    doc.head.append(style);
  }
  const count = trace.steps.length;
  const lines = trace.source.text.split("\n");
  root.innerHTML = `
    <div class="rr-app">
      <header class="rr-head">
        <h1>${esc(trace.source.file)}</h1>
        <span class="rr-entry">${esc(trace.source.entry)}</span>
        ${trace.truncated ? '<span class="rr-mark" title="The run went on past the step limit">truncated</span>' : ""}
        ${trace.stopped ? `<span class="rr-mark" title="The run was stopped ${STOPS[trace.stopped].how}">${STOPS[trace.stopped].badge}</span>` : ""}
        ${options.mark === false ? "" : '<a class="rr-brand" href="https://github.com/RunReel/RunReel" target="_blank" rel="noopener">made with <b>RunReel</b></a>'}
        <button type="button" class="rr-theme" aria-label="Switch theme">Theme: auto</button>
      </header>
      <pre class="rr-code" aria-label="Source code">${lines.map((line, i) => `<div class="rr-ln" data-line="${i + 1}"><span>${i + 1}</span><span>${esc(line) || " "}</span></div>`).join("")}</pre>
      <section class="rr-visual" aria-label="Data structures"></section>
      <section class="rr-vars" aria-label="Variables"></section>
      <footer class="rr-time">
        <button type="button" data-act="first" aria-label="First step">⏮</button>
        <button type="button" data-act="back" aria-label="Step back">◀</button>
        <button type="button" data-act="toggle" aria-label="Play">▶</button>
        <button type="button" data-act="forward" aria-label="Step forward">▶▶</button>
        <button type="button" data-act="last" aria-label="Last step">⏭</button>
        <input type="range" min="0" max="${Math.max(count - 1, 0)}" value="0" aria-label="Step">
        <select aria-label="Speed">${SPEEDS.map((s) => `<option value="${s}"${s === 1 ? " selected" : ""}>${s}×</option>`).join("")}</select>
        <span class="rr-count" aria-live="polite"></span>
      </footer>
    </div>`;
  const $ = <T extends Element>(selector: string) => root.querySelector(selector) as T;
  const code = $<HTMLElement>(".rr-code");
  const visual = $<HTMLElement>(".rr-visual");
  const vars = $<HTMLElement>(".rr-vars");
  const range = $<HTMLInputElement>(".rr-time input");
  const speed = $<HTMLSelectElement>(".rr-time select");
  const counter = $<HTMLElement>(".rr-count");
  const playButton = $<HTMLButtonElement>('[data-act="toggle"]');
  const themeButton = $<HTMLButtonElement>(".rr-theme");
  const lineEls = [...code.querySelectorAll<HTMLElement>(".rr-ln")];
  const first = firstSteps(trace.steps);
  const scene = new SceneView(visual);
  let current = 0;
  let timer: ReturnType<typeof setInterval> | undefined;

  const show = (n: number) => {
    if (count === 0) return;
    current = Math.min(Math.max(n, 0), count - 1);
    const state = stateAt(trace.steps, current);
    const prev = current > 0 ? stateAt(trace.steps, current - 1) : undefined;
    for (const el of lineEls) {
      const line = Number(el.dataset.line);
      el.classList.toggle("rr-now", line === state.line);
      el.classList.toggle("rr-ran", (first.get(line) ?? Infinity) <= current && line !== state.line);
    }
    lineEls[state.line - 1]?.scrollIntoView?.({ block: "nearest" });
    const views = inferViews(state, prev);
    if (views.length) scene.draw(composeScene(views));
    else scene.clear("No array, tree or graph at this step. The variables are below.");
    vars.innerHTML = variablesHtml(state, prev, trace, current, current === count - 1);
    range.value = String(current);
    counter.textContent = `step ${current + 1} / ${count} · line ${state.line}`;
    const hash = `#step=${current}`;
    try {
      if (location.hash !== hash) history.replaceState(null, "", hash);
    } catch {
      // Some browsers refuse history updates on file:// pages; the link is a convenience only.
    }
  };
  const stop = () => {
    if (timer !== undefined) clearInterval(timer);
    timer = undefined;
    playButton.textContent = "▶";
    playButton.setAttribute("aria-label", "Play");
  };
  const play = () => {
    if (current >= count - 1) show(0);
    stop();
    timer = setInterval(() => (current >= count - 1 ? stop() : show(current + 1)), 1000 / (BASE_STEPS_PER_SECOND * Number(speed.value)));
    playButton.textContent = "⏸";
    playButton.setAttribute("aria-label", "Pause");
  };
  const act = (action: string | undefined) => {
    if (action === "toggle") return timer === undefined ? play() : stop();
    if (action) stop();
    if (action === "back") show(current - 1);
    if (action === "forward") show(current + 1);
    if (action === "first") show(0);
    if (action === "last") show(count - 1);
  };

  root.querySelectorAll<HTMLButtonElement>("[data-act]").forEach((b) => b.addEventListener("click", () => act(b.dataset.act)));
  range.addEventListener("input", () => {
    stop();
    show(Number(range.value));
  });
  speed.addEventListener("change", () => timer !== undefined && play());
  doc.addEventListener("keydown", (event) => {
    const target = event.target as HTMLElement | null;
    if (event.ctrlKey || event.metaKey || event.altKey || target?.matches?.("input, select, textarea")) return;
    const action = actionForKey(event.key);
    if (!action) return;
    event.preventDefault();
    act(action);
  });
  const themes = ["auto", "light", "dark"] as const;
  let theme = 0;
  themeButton.addEventListener("click", () => {
    theme = (theme + 1) % themes.length;
    const name = themes[theme]!;
    if (name === "auto") delete doc.documentElement.dataset.theme;
    else doc.documentElement.dataset.theme = name;
    themeButton.textContent = `Theme: ${name}`;
  });
  addEventListener("hashchange", () => show(stepFromHash(location.hash, count)));
  show(stepFromHash(location.hash, count));
  return {
    show,
    get step() {
      return current;
    },
  };
}

function variablesHtml(state: State, prev: State | undefined, trace: TraceFile, n: number, last: boolean): string {
  const before = new Map(prev?.stack.map((f) => [f.fid, f.locals]) ?? []);
  const frames = [...state.stack].reverse().map((frame) => {
    const old = before.get(frame.fid);
    const rows = Object.entries(frame.locals).map(([name, value]) => {
      const text = formatValue(value, state.heap, 1);
      const changed = !!old && (!(name in old) || formatValue(old[name], prev!.heap, 1) !== text);
      return `<dt>${esc(name)}</dt><dd${changed ? ' class="rr-new"' : ""}>${esc(text)}</dd>`;
    });
    return `<div class="rr-frame"><h2>${esc(frame.fn)}()</h2><dl>${rows.join("") || "<dd>no variables yet</dd>"}</dl></div>`;
  });
  const events: string[] = [];
  if (state.ev === "return") events.push(`<p class="rr-event">↩ returns ${esc(formatValue(state.ret, state.heap, 1))}</p>`);
  if (state.ev === "exception") events.push(`<p class="rr-event rr-error">⚠ ${esc(state.exc ?? "exception")}</p>`);
  if (last && trace.error) events.push(`<p class="rr-event rr-error">The run ended with ${esc(trace.error)}</p>`);
  const note = endNote(trace);
  if (last && note) events.push(`<p class="rr-event">${esc(note)}</p>`);
  const printed = printedBy(trace.stdout, n);
  if (printed) events.push(`<pre class="rr-out" aria-label="Printed output">${esc(printed)}</pre>`);
  return events.join("") + frames.join("");
}

/** Keeps one SVG and moves its keyed elements between scenes, so CSS can animate the moves. */
class SceneView {
  private svg: SVGSVGElement | undefined;
  private readonly items = new Map<string, SVGGElement>();
  private readonly ns = "http://www.w3.org/2000/svg";

  constructor(private readonly host: HTMLElement) {}

  draw(scene: Scene): void {
    const doc = this.host.ownerDocument;
    if (!this.svg) {
      this.host.innerHTML = "";
      this.svg = doc.createElementNS(this.ns, "svg") as SVGSVGElement;
      this.svg.classList.add("rr-scene");
      this.svg.innerHTML = ARROW_DEFS;
      this.host.append(this.svg);
    }
    this.svg.setAttribute("viewBox", `0 0 ${scene.width} ${scene.height}`);
    this.svg.setAttribute("width", String(scene.width));
    this.svg.setAttribute("height", String(scene.height));
    const seen = new Set<string>();
    for (const item of scene.items) {
      seen.add(item.key);
      let el = this.items.get(item.key);
      if (!el) {
        el = doc.createElementNS(this.ns, "g") as SVGGElement;
        el.dataset.key = item.key;
        this.items.set(item.key, el);
      }
      this.svg.append(el); // keeps the scene's drawing order: edges under nodes
      el.setAttribute("class", `rr-${item.type} ${item.cls}`.trim());
      if (item.type !== "line") el.style.transform = `translate(${round(item.x)}px, ${round(item.y)}px)`;
      const inner = itemInner(item as Item);
      if (el.dataset.inner !== inner) {
        el.innerHTML = inner;
        el.dataset.inner = inner;
      }
    }
    for (const [key, el] of this.items) {
      if (!seen.has(key)) {
        el.remove();
        this.items.delete(key);
      }
    }
  }

  clear(message: string): void {
    this.svg = undefined;
    this.items.clear();
    this.host.innerHTML = `<p class="rr-empty">${esc(message)}</p>`;
  }
}

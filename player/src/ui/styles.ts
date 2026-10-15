/** The player's stylesheet. Colours come from the Okabe–Ito palette, which stays distinct for colour-blind viewers. */
export const STYLES = `
:root {
  --rr-bg: #fbfaf7; --rr-surface: #ffffff; --rr-ink: #1d2433; --rr-muted: #6b7280; --rr-line: #d6d3cc;
  --rr-code-bg: #f3f1ec; --rr-hl: #fff1c2; --rr-ran: #e9e6de;
  --rr-blue: #0072b2; --rr-orange: #e69f00; --rr-red: #d55e00; --rr-green: #009e73; --rr-sky: #56b4e9;
  --rr-changed-bg: #fdecc8; --rr-current-bg: #fde2cf; --rr-next-bg: #dbeefa; --rr-visited-bg: #d4f0e5;
  --rr-font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --rr-mono: ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --rr-bg: #14171f; --rr-surface: #1c2130; --rr-ink: #e6e8ee; --rr-muted: #9aa3b5; --rr-line: #343b4e;
    --rr-code-bg: #181c27; --rr-hl: #4a3f12; --rr-ran: #222838;
    --rr-changed-bg: #4d3a0b; --rr-current-bg: #50290d; --rr-next-bg: #10364f; --rr-visited-bg: #0e3d31;
  }
}
:root[data-theme="dark"] {
  --rr-bg: #14171f; --rr-surface: #1c2130; --rr-ink: #e6e8ee; --rr-muted: #9aa3b5; --rr-line: #343b4e;
  --rr-code-bg: #181c27; --rr-hl: #4a3f12; --rr-ran: #222838;
  --rr-changed-bg: #4d3a0b; --rr-current-bg: #50290d; --rr-next-bg: #10364f; --rr-visited-bg: #0e3d31;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: var(--rr-bg); color: var(--rr-ink); font-family: var(--rr-font); }
.rr-app { display: grid; grid-template-columns: minmax(280px, 2fr) 3fr; grid-template-rows: auto 1fr auto auto;
  grid-template-areas: "head head" "code visual" "code vars" "time time"; height: 100vh; gap: 0; }
.rr-head { grid-area: head; display: flex; align-items: baseline; gap: 12px; padding: 10px 16px; border-bottom: 1px solid var(--rr-line); }
.rr-head h1 { font-size: 15px; margin: 0; font-weight: 600; }
.rr-head .rr-entry { font-family: var(--rr-mono); font-size: 13px; color: var(--rr-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rr-head .rr-theme { margin-left: auto; }
.rr-code { grid-area: code; overflow: auto; background: var(--rr-code-bg); border-right: 1px solid var(--rr-line);
  font-family: var(--rr-mono); font-size: 13px; line-height: 1.6; padding: 8px 0; }
.rr-code .rr-ln { display: grid; grid-template-columns: 3.2em 1fr; white-space: pre; padding-right: 12px; }
.rr-code .rr-ln > span:first-child { color: var(--rr-muted); text-align: right; padding-right: 12px; user-select: none; }
.rr-code .rr-ran { background: var(--rr-ran); }
.rr-code .rr-now { background: var(--rr-hl); box-shadow: inset 3px 0 0 var(--rr-orange); }
.rr-visual { grid-area: visual; overflow: auto; padding: 4px; }
.rr-visual svg { display: block; max-width: none; }
.rr-empty { color: var(--rr-muted); padding: 16px; font-size: 14px; }
.rr-vars { grid-area: vars; overflow: auto; max-height: 34vh; border-top: 1px solid var(--rr-line); padding: 8px 16px; font-size: 13px; }
.rr-frame { margin: 0 0 8px; }
.rr-frame h2 { font-size: 12px; font-weight: 600; margin: 0 0 4px; color: var(--rr-muted); font-family: var(--rr-mono); }
.rr-frame dl { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 0; font-family: var(--rr-mono); }
.rr-frame dt { color: var(--rr-blue); } .rr-frame dd { margin: 0; overflow-wrap: anywhere; }
.rr-frame dd.rr-new { background: var(--rr-changed-bg); border-radius: 3px; }
.rr-event { font-family: var(--rr-mono); margin: 4px 0; }
.rr-event.rr-error { color: var(--rr-red); }
.rr-out { font-family: var(--rr-mono); white-space: pre-wrap; background: var(--rr-code-bg); padding: 6px 8px; border-radius: 4px; margin: 4px 0 0; }
.rr-time { grid-area: time; display: flex; align-items: center; gap: 8px; padding: 8px 16px; border-top: 1px solid var(--rr-line); flex-wrap: wrap; }
.rr-time input[type=range] { flex: 1; min-width: 160px; accent-color: var(--rr-blue); }
.rr-time button, .rr-time select, .rr-head button { font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 6px;
  border: 1px solid var(--rr-line); background: var(--rr-surface); color: var(--rr-ink); cursor: pointer; }
.rr-time button:focus-visible, .rr-time input:focus-visible, .rr-head button:focus-visible { outline: 2px solid var(--rr-blue); outline-offset: 2px; }
.rr-count { font-family: var(--rr-mono); font-size: 13px; color: var(--rr-muted); min-width: 9em; text-align: right; }
.rr-mark { font-size: 12px; color: var(--rr-muted); } .rr-mark a { color: inherit; }
/* Scene */
.rr-box rect { fill: var(--rr-surface); stroke: var(--rr-line); stroke-width: 1.5; }
.rr-box.rr-changed rect { fill: var(--rr-changed-bg); stroke: var(--rr-orange); stroke-width: 2; }
.rr-box text, .rr-circle text { fill: var(--rr-ink); font: 600 14px var(--rr-mono); }
.rr-index text { fill: var(--rr-muted); font: 11px var(--rr-mono); }
.rr-pointer text { fill: var(--rr-blue); font: 600 12px var(--rr-mono); }
.rr-title text { fill: var(--rr-ink); font: 600 13px var(--rr-mono); }
.rr-more text { fill: var(--rr-muted); font: 12px var(--rr-font); }
.rr-circle circle { fill: var(--rr-surface); stroke: var(--rr-line); stroke-width: 2; }
.rr-circle .rr-sub { fill: var(--rr-muted); font: 11px var(--rr-mono); }
.rr-circle.rr-current circle { fill: var(--rr-current-bg); stroke: var(--rr-red); stroke-width: 2.5; }
.rr-circle.rr-next circle { fill: var(--rr-next-bg); stroke: var(--rr-blue); stroke-width: 2.5; }
.rr-circle.rr-visited circle { fill: var(--rr-visited-bg); stroke: var(--rr-green); }
.rr-line line { stroke: var(--rr-muted); stroke-width: 1.5; }
.rr-line.rr-active line { stroke: var(--rr-red); stroke-width: 3; }
.rr-line .rr-weight { fill: var(--rr-muted); font: 11px var(--rr-mono); }
.rr-line.rr-active .rr-weight { fill: var(--rr-red); font-weight: 700; }
.rr-arrowhead { fill: var(--rr-muted); }
.rr-sub, .rr-weight, .rr-pointer text, .rr-index text { paint-order: stroke; stroke: var(--rr-bg); stroke-width: 4px; stroke-linejoin: round; }
.rr-scene g[data-key] { transition: transform 260ms ease-out; }
.rr-scene line { transition: x1 260ms, y1 260ms, x2 260ms, y2 260ms; }
@media (prefers-reduced-motion: reduce) { .rr-scene g[data-key], .rr-scene line { transition: none; } }
@media (max-width: 760px) {
  .rr-app { grid-template-columns: 1fr; grid-template-rows: auto auto 40vh auto auto; grid-template-areas: "head" "visual" "code" "vars" "time"; height: auto; }
  .rr-code { border-right: 0; max-height: 40vh; } .rr-vars { max-height: none; }
}
`;

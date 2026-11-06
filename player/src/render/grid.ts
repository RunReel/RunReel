import type { GridView } from "../view/infer";
import type { Item } from "./scene";

const SIZE = 30; // a cell is square at this size, and wider only if its text needs it
const GAP = 2;
const CHAR = 8.6; // width of one 14px monospace character
const TOP = 16; // room for the column numbers

/**
 * A grid with its row and column numbers, changed cells highlighted, the cell the code is on
 * outlined, and the cells the current line reads shaded, with an arrow from any that isn't a
 * neighbour, so a DP table shows how each cell is worked out. A window of a big grid keeps the
 * grid's own numbers.
 */
export function renderGrid(view: GridView, x0: number, y0: number): { items: Item[]; width: number; height: number } {
  const rows = view.rows.length;
  const cols = view.rows[0]?.length ?? 0;
  const longest = Math.max(1, ...view.rows.flat().map((cell) => cell.text.length));
  const w = Math.max(SIZE, Math.ceil(longest * CHAR + 10));
  const h = SIZE;
  const numbers = Math.ceil(String(view.top + rows - 1).length * 7 + 10); // room for the row numbers
  const ox = x0 + numbers;
  const oy = y0 + TOP;
  const at = (row: number, col: number) => ({ x: ox + (col - view.left) * (w + GAP), y: oy + (row - view.top) * (h + GAP) });
  const items: Item[] = [];
  const read = new Set(view.focus ? view.deps.map((d) => `${d.row}:${d.col}`) : []);
  for (let c = 0; c < cols; c++) {
    const col = view.left + c;
    items.push({ key: `${view.key}:col:${col}`, type: "label", x: at(view.top, col).x + w / 2, y: oy - 5, text: String(col), cls: "rr-index", anchor: "middle" });
  }
  view.rows.forEach((cells, r) => {
    const row = view.top + r;
    items.push({ key: `${view.key}:row:${row}`, type: "label", x: ox - 6, y: at(row, view.left).y + h / 2 + 4, text: String(row), cls: "rr-index", anchor: "end" });
    cells.forEach((cell, c) => {
      const p = at(row, view.left + c);
      const cls = cell.changed ? "rr-changed" : read.has(`${row}:${view.left + c}`) ? "rr-read" : "";
      items.push({ key: cell.key, type: "box", x: p.x, y: p.y, w, h, text: cell.text, cls });
    });
  });
  const inside = (cell: { row: number; col: number }) =>
    cell.row >= view.top && cell.row < view.top + rows && cell.col >= view.left && cell.col < view.left + cols;
  if (view.focus && inside(view.focus)) {
    const f = at(view.focus.row, view.focus.col);
    const fx = f.x + w / 2;
    const fy = f.y + h / 2;
    const far = (dep: { row: number; col: number }) => Math.max(Math.abs(dep.row - view.focus!.row), Math.abs(dep.col - view.focus!.col)) > 1;
    view.deps.filter((dep) => inside(dep) && far(dep)).forEach((dep, i) => {
      const d = at(dep.row, dep.col);
      const dx = d.x + w / 2;
      const dy = d.y + h / 2;
      const len = Math.hypot(fx - dx, fy - dy) || 1;
      const ux = (fx - dx) / len;
      const uy = (fy - dy) / len;
      const edge = Math.min(w, h) / 2 + 2; // from the edge of one cell to the edge of the other
      items.push({ key: `${view.key}:dep:${i}`, type: "line", x1: dx + ux * edge, y1: dy + uy * edge, x2: fx - ux * edge, y2: fy - uy * edge, cls: "rr-dep", arrow: true });
    });
    // Keyed by grid, so the outline slides from cell to cell as the code moves on.
    items.push({ key: `${view.key}:focus`, type: "box", x: f.x - 2, y: f.y - 2, w: w + 4, h: h + 4, text: "", cls: "rr-focus" });
  }
  const partial = view.top > 0 || view.left > 0 || view.top + rows < view.height || view.left + cols < view.width;
  if (partial) {
    const note = `rows ${view.top}–${view.top + rows - 1} of ${view.height} · columns ${view.left}–${view.left + cols - 1} of ${view.width}`;
    items.push({ key: `${view.key}:window`, type: "label", x: ox, y: oy + rows * (h + GAP) + 14, text: note, cls: "rr-more" });
  }
  return { items, width: numbers + cols * (w + GAP), height: TOP + rows * (h + GAP) + (partial ? 20 : 0) };
}

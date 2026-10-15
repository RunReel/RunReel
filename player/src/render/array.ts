import type { ArrayView } from "../view/infer";
import type { Item } from "./scene";

const CELL = 44;
const GAP = 4;
const HEIGHT = 36;
const CHAR = 8.6; // width of one 14px monospace character

/** A cell is at least CELL wide, wider if its text needs it. */
const cellWidth = (text: string) => Math.max(CELL, Math.ceil(text.length * CHAR + 16));

/** Cells in a row with their indices, changed cells highlighted, and pointers underneath. */
export function renderArray(view: ArrayView, x0: number, y0: number): { items: Item[]; width: number; height: number } {
  const items: Item[] = [];
  const left: number[] = [];
  let x = x0;
  view.cells.forEach((cell, i) => {
    const w = cellWidth(cell.text);
    left.push(x);
    items.push({ key: cell.key, type: "box", x, y: y0, w, h: HEIGHT, text: cell.text, cls: cell.changed ? "rr-changed" : "" });
    items.push({ key: `${cell.key}:index`, type: "label", x: x + w / 2, y: y0 - 6, text: String(i), cls: "rr-index", anchor: "middle" });
    x += w + GAP;
  });
  left.push(x); // a pointer may sit one past the end, as hi = len(a) often does
  if (view.more) {
    items.push({ key: `${view.key}:more`, type: "label", x, y: y0 + HEIGHT / 2 + 4, text: `+${view.more} more`, cls: "rr-more" });
  }
  const stacked = new Map<number, number>();
  for (const pointer of view.pointers) {
    const level = stacked.get(pointer.index) ?? 0;
    stacked.set(pointer.index, level + 1);
    const at = left[pointer.index]! + (pointer.index < view.cells.length ? cellWidth(view.cells[pointer.index]!.text) : CELL) / 2;
    // Keyed by name, so a pointer slides from cell to cell as it moves.
    items.push({ key: `${view.key}:ptr:${pointer.name}`, type: "label", x: at, y: y0 + HEIGHT + 18 + level * 16, text: `↑ ${pointer.name}`, cls: "rr-pointer", anchor: "middle" });
  }
  const levels = Math.max(0, ...stacked.values());
  const width = Math.max(x - x0, CELL) + (view.more ? 80 : 0);
  return { items, width, height: HEIGHT + 10 + levels * 16 };
}

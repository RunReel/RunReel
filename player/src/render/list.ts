import type { ListEnd, ListView } from "../view/infer";
import type { Item } from "./scene";

const CELL = 44;
const HEIGHT = 36;
const CHAR = 8.6; // width of one 14px monospace character
const SMALL = 7.3; // width of one 12px monospace character, as None and "3 more" are drawn
const GAP = 30; // room for the arrow from one node to the next
const LANE = 12; // height of each lane over a row, for arrows to a node further along it
const POINTER = 16; // height of one pointer label under a node
const ROW_GAP = 16;

const nodeWidth = (text: string) => Math.max(CELL, Math.ceil(text.length * CHAR + 16));
const textWidth = (text: string) => Math.ceil(text.length * SMALL);

interface Point {
  x: number;
  y: number;
}

interface Placed extends Point {
  w: number;
}

/**
 * Linked list: each chain of nodes on a row of its own, in next order, with an arrow from each
 * node to the next and None at the end. An arrow that changed this step is highlighted, so
 * reversing a list shows each next pointer turning round, and the variables pointing at nodes
 * sit underneath them. A doubly linked list's prev arrows run back along the bottom of the row.
 * An arrow to a node further along the same row, as a loop makes, goes over the top; one to a
 * node in another row, where two lists join, goes straight there.
 */
export function renderList(view: ListView, x0: number, y0: number): { items: Item[]; width: number; height: number } {
  const items: Item[] = [];
  const place = new Map<string, Placed>();
  const doubly = Object.values(view.nodes).some((node) => node.prev);
  const nextY = doubly ? HEIGHT / 3 : HEIGHT / 2;
  const prevY = (HEIGHT * 2) / 3;
  const pointed = new Map<string, number>();
  for (const pointer of view.pointers) pointed.set(pointer.node, (pointed.get(pointer.node) ?? 0) + 1);

  // Place every node first, so an arrow can go to a node in a later row.
  const rowOf = new Map<string, number>();
  view.rows.forEach((row, r) => row.nodes.forEach((id) => rowOf.set(id, r)));
  // Whether an arrow goes over the top: to a node in its own row other than the one beside it.
  const overRow = (from: string, to: string | null | undefined, beside: string | undefined) => !!to && to !== beside && rowOf.get(to) === rowOf.get(from);
  const tops: number[] = [];
  let y = y0;
  let width = 0;
  view.rows.forEach((row, r) => {
    const loop = row.end.kind === "node" && rowOf.get(row.end.to) === r;
    const backs = row.nodes.some((id, i) => overRow(id, view.nodes[id]!.prev?.to, row.nodes[i - 1]));
    const top = y + LANE * (backs ? 2 : loop ? 1 : 0);
    tops.push(top);
    let x = x0 + (row.skipped ? textWidth(skippedText(row.skipped)) + GAP : 0);
    for (const id of row.nodes) {
      const w = nodeWidth(view.nodes[id]!.text);
      place.set(id, { x, y: top, w });
      x += w + GAP;
    }
    const label = endText(row.end);
    width = Math.max(width, (label ? x + textWidth(label) : x - GAP) - x0);
    const deepest = Math.max(0, ...row.nodes.map((id) => pointed.get(id) ?? 0));
    y = top + HEIGHT + (deepest ? 10 + deepest * POINTER : 0) + ROW_GAP;
  });

  view.rows.forEach((row, r) => {
    const top = tops[r]!;
    if (row.skipped) {
      const first = place.get(row.nodes[0]!)!;
      items.push({ key: `list:skipped:${r}`, type: "label", x: x0, y: top + nextY + 4, text: skippedText(row.skipped), cls: "rr-null" });
      items.push(arrow(`list:skipped:${r}:next`, { x: first.x - GAP + 6, y: top + nextY }, { x: first.x - 2, y: top + nextY }, "rr-edge"));
    }
    row.nodes.forEach((id, i) => {
      const node = view.nodes[id]!;
      const p = place.get(id)!;
      items.push({ key: `list:${id}`, type: "box", x: p.x, y: p.y, w: p.w, h: HEIGHT, text: node.text, cls: node.changed ? "rr-changed" : "" });
      const cls = node.relinked ? "rr-edge rr-active" : "rr-edge";
      const from = { x: p.x + p.w, y: p.y + nextY };
      const next = row.nodes[i + 1] ?? (row.end.kind === "node" ? row.end.to : undefined);
      const q = next !== undefined ? place.get(next) : undefined;
      if (q && next === row.nodes[i + 1]) {
        items.push(arrow(`list:next:${id}`, from, { x: q.x - 2, y: q.y + nextY }, cls));
      } else if (q && rowOf.get(next!) === r) {
        items.push(...overTop(`list:next:${id}`, p, q, top - LANE + 2, cls, id === next));
      } else if (q) {
        items.push(arrow(`list:next:${id}`, from, boxEdge(from, q), cls));
      } else {
        // None, or nodes that aren't drawn
        items.push(arrow(`list:next:${id}`, from, { x: from.x + GAP - 6, y: from.y }, cls));
        items.push({ key: `list:end:${id}`, type: "label", x: from.x + GAP - 2, y: from.y + 4, text: endText(row.end) || "…", cls: "rr-null" });
      }
      const back = node.prev?.to;
      const b = back ? place.get(back) : undefined;
      if (!b) return;
      const bcls = node.prev!.relinked ? "rr-edge rr-active" : "rr-edge";
      const start = { x: p.x, y: p.y + prevY };
      if (row.nodes[i - 1] === back) items.push(arrow(`list:prev:${id}`, start, { x: b.x + b.w + 2, y: b.y + prevY }, bcls));
      else if (rowOf.get(back!) === r) items.push(...overTop(`list:prev:${id}`, p, b, top - 2 * LANE + 2, bcls, id === back));
      else items.push(arrow(`list:prev:${id}`, start, boxEdge(start, b), bcls));
    });
  });

  // Keyed by name, so a pointer slides from node to node, and from row to row, as it moves.
  const stacked = new Map<string, number>();
  for (const pointer of view.pointers) {
    const p = place.get(pointer.node);
    if (!p) continue;
    const level = stacked.get(pointer.node) ?? 0;
    stacked.set(pointer.node, level + 1);
    items.push({ key: `list:ptr:${pointer.name}`, type: "label", x: p.x + p.w / 2, y: p.y + HEIGHT + 18 + level * POINTER, text: `↑ ${pointer.name}`, cls: "rr-pointer", anchor: "middle" });
  }
  if (view.more) {
    items.push({ key: "list:more", type: "label", x: x0, y: y + 2, text: `${view.more} more ${view.more === 1 ? "list" : "lists"} not shown`, cls: "rr-more" });
    y += 22;
  }
  return { items, width: Math.max(width, CELL), height: y - y0 - ROW_GAP };
}

function endText(end: ListEnd): string {
  if (end.kind === "none") return "None";
  if (end.kind === "more") return end.count ? `${end.count} more` : "…";
  return "";
}

const skippedText = (count: number) => `${count} more`;

function arrow(key: string, from: Point, to: Point, cls: string): Item {
  return { key, type: "line", x1: from.x, y1: from.y, x2: to.x, y2: to.y, cls, arrow: true };
}

/** An arrow up from one node, along a lane over the row and down into another node; a node's
 * arrow to itself leaves from its right side and comes back into its left. */
function overTop(key: string, from: Placed, to: Placed, lane: number, cls: string, self: boolean): Item[] {
  const sx = from.x + from.w * (self ? 0.7 : 0.5);
  const tx = to.x + to.w * (self ? 0.3 : 0.5);
  return [
    { key: `${key}:up`, type: "line", x1: sx, y1: from.y, x2: sx, y2: lane, cls },
    { key: `${key}:over`, type: "line", x1: sx, y1: lane, x2: tx, y2: lane, cls },
    arrow(key, { x: tx, y: lane }, { x: tx, y: to.y - 2 }, cls),
  ];
}

/** Where the line from a point to the middle of a node crosses the edge of its box, just outside. */
function boxEdge(from: Point, box: Placed): Point {
  const cx = box.x + box.w / 2;
  const cy = box.y + HEIGHT / 2;
  const dx = from.x - cx;
  const dy = from.y - cy;
  const scale = Math.min(1, 1 / Math.max(Math.abs(dx) / (box.w / 2 + 2), Math.abs(dy) / (HEIGHT / 2 + 2), 1e-9));
  return { x: cx + dx * scale, y: cy + dy * scale };
}

import type { TreeView } from "../view/infer";
import type { Item } from "./scene";

const R = 17;
const DX = 44;
const DY = 60;

/**
 * Binary tree, laid out in order: a node's x is its rank in an in-order walk and its y is its
 * depth. Parents sit between their subtrees, nothing overlaps, and a node only moves when a
 * node is inserted to its left.
 */
export function renderTree(view: TreeView, x0: number, y0: number): { items: Item[]; width: number; height: number } {
  const pos = new Map<string, { x: number; y: number }>();
  let rank = 0;
  let depthMax = 0;
  const walk = (id: string | undefined, depth: number, seen: Set<string>) => {
    if (!id || seen.has(id) || !view.nodes[id]) return;
    seen.add(id);
    const node = view.nodes[id]!;
    walk(node.left, depth + 1, seen);
    pos.set(id, { x: x0 + R + rank * DX, y: y0 + R + depth * DY });
    rank += 1;
    depthMax = Math.max(depthMax, depth);
    walk(node.right, depth + 1, seen);
  };
  walk(view.root, 0, new Set());
  const items: Item[] = [];
  for (const [id, p] of pos) {
    const node = view.nodes[id]!;
    for (const childId of [node.left, node.right]) {
      const c = childId ? pos.get(childId) : undefined;
      if (!c) continue;
      const len = Math.hypot(c.x - p.x, c.y - p.y);
      const ux = (c.x - p.x) / len;
      const uy = (c.y - p.y) / len;
      items.push({ key: `edge:${id}->${childId}`, type: "line", x1: p.x + ux * R, y1: p.y + uy * R, x2: c.x - ux * R, y2: c.y - uy * R, cls: "rr-edge" });
    }
  }
  for (const [id, p] of pos) {
    const node = view.nodes[id]!;
    const marked = node.marks.length > 0;
    items.push({ key: `node:${id}`, type: "circle", x: p.x, y: p.y, r: R, text: node.text, cls: marked ? "rr-current" : "", ...(marked ? { sub: node.marks.join(", ") } : {}) });
  }
  return { items, width: Math.max(rank, 1) * DX, height: (depthMax + 1) * DY };
}

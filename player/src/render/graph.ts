import type { GraphView } from "../view/infer";
import type { Item } from "./scene";

const R = 18;

/**
 * Graph with its nodes on a circle, in the order the dict lists them, so a node keeps its
 * place from step to step. Edges are arrows with their weights; the node being processed,
 * the neighbour being looked at and the edge between them are highlighted.
 */
export function renderGraph(view: GraphView, x0: number, y0: number): { items: Item[]; width: number; height: number } {
  const n = view.nodes.length;
  const radius = Math.max(70, (n * (2 * R + 30)) / (2 * Math.PI));
  const cx = x0 + radius + R + 20;
  const cy = y0 + radius + R;
  const pos = new Map<string, { x: number; y: number }>();
  view.nodes.forEach((node, i) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(n, 1);
    pos.set(node.key, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) });
  });
  const items: Item[] = [];
  const pairs = new Set(view.edges.map((e) => `${e.from}|${e.to}`));
  for (const edge of view.edges) {
    const a = pos.get(edge.from)!;
    const b = pos.get(edge.to)!;
    if (edge.from === edge.to) continue;
    const len = Math.hypot(b.x - a.x, b.y - a.y);
    const ux = (b.x - a.x) / len;
    const uy = (b.y - a.y) / len;
    // Bend two-way edges apart, so both arrows and weights stay readable.
    const bend = pairs.has(`${edge.to}|${edge.from}`) ? 6 : 0;
    const ox = -uy * bend;
    const oy = ux * bend;
    items.push({
      key: `edge:${edge.key}`,
      type: "line",
      x1: a.x + ux * R + ox,
      y1: a.y + uy * R + oy,
      x2: b.x - ux * (R + 2) + ox,
      y2: b.y - uy * (R + 2) + oy,
      cls: edge.active ? "rr-edge rr-active" : "rr-edge",
      arrow: true,
      ...(edge.weight !== undefined ? { text: edge.weight } : {}),
    });
  }
  for (const node of view.nodes) {
    const p = pos.get(node.key)!;
    items.push({ key: `node:${node.key}`, type: "circle", x: p.x, y: p.y, r: R, text: node.text, cls: node.state === "none" ? "" : `rr-${node.state}`, ...(node.sub !== undefined ? { sub: node.sub } : {}) });
  }
  return { items, width: 2 * (radius + R + 20), height: 2 * (radius + R) + 20 };
}

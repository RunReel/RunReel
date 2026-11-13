import type { GraphEdge, GraphView } from "../view/infer";
import type { Item } from "./scene";

const R = 18;
const LANE = 26; // how far apart the tops of the arcs between the same two nodes are, at most

/**
 * Graph with its nodes on a circle, in the order the dict lists them, so a node keeps its
 * place from step to step. The circle grows with the number of nodes and, in steps, with how
 * many edges each has, so a busy graph gets more room. Edges are arrows with their weights, or
 * plain lines if the graph is undirected; the node being processed, the neighbour being looked
 * at and the edge between them are highlighted. Edges between the same two nodes fan out as arcs
 * with their weights at the top, one direction's on one side of the straight line and the
 * other's on the other, like lanes of a road; a lone edge stays straight. An edge from a node to
 * itself is a loop pointing away from the middle.
 */
export function renderGraph(view: GraphView, x0: number, y0: number): { items: Item[]; width: number; height: number } {
  const n = view.nodes.length;
  // Edges between the same two nodes, one direction's first, then the other's.
  const groups = new Map<string, GraphEdge[]>();
  for (const edge of view.edges) {
    if (edge.from === edge.to) continue;
    const pair = [edge.from, edge.to].sort().join("|");
    groups.set(pair, [...(groups.get(pair) ?? []), edge]);
  }
  for (const [pair, group] of groups) {
    const first = pair.split("|")[0];
    group.sort((a, b) => Number(a.from !== first) - Number(b.from !== first));
  }
  // Edges per node, in half steps from 1.5 up: a sparse graph keeps the plain circle.
  const busy = Math.min(4, Math.max(0, Math.floor((2 * view.edges.length) / Math.max(n, 1)) - 2));
  const widest = Math.max(1, ...[...groups.values()].map((g) => g.length));
  const gap = 2 * R + 30 + busy * 12 + (widest - 1) * 10; // room between neighbours on the circle
  const radius = Math.max(80 + busy * 15, (n * gap) / (2 * Math.PI));
  const extra = ((widest - 1) * LANE) / 2; // room for the outermost arc's top
  const cx = x0 + radius + R + 20 + extra;
  const cy = y0 + radius + R + extra;
  const pos = new Map<string, { x: number; y: number }>();
  view.nodes.forEach((node, i) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / Math.max(n, 1);
    pos.set(node.key, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) });
  });
  const items: Item[] = [];
  for (const edge of view.edges) {
    const a = pos.get(edge.from)!;
    const b = pos.get(edge.to)!;
    const cls = edge.active ? "rr-edge rr-active" : "rr-edge";
    const tips = { arrow: view.directed, ...(edge.weight !== undefined ? { text: edge.weight } : {}) };
    if (edge.from === edge.to) {
      items.push(...selfLoop(edge.key, a, { x: cx, y: cy }, edge.nth, cls, tips));
      continue;
    }
    const pair = [edge.from, edge.to].sort();
    const group = groups.get(pair.join("|"))!;
    const p = pos.get(pair[0]!)!;
    const q = pos.get(pair[1]!)!;
    const len = Math.hypot(q.x - p.x, q.y - p.y);
    // The arcs' tops are LANE apart, or closer between near neighbours, so no arc balloons.
    const lane = Math.min(LANE, (0.3 * len) / Math.max((group.length - 1) / 2, 1));
    const top = (group.indexOf(edge) - (group.length - 1) / 2) * lane;
    if (top === 0) {
      const ux = (b.x - a.x) / len;
      const uy = (b.y - a.y) / len;
      items.push({ key: `edge:${edge.key}`, type: "line", x1: a.x + ux * R, y1: a.y + uy * R, x2: b.x - ux * (R + 2), y2: b.y - uy * (R + 2), cls, ...tips });
      continue;
    }
    // A curve's top is halfway to its control point, which sits to one side of the line from p to q.
    const via = { x: (p.x + q.x) / 2 - ((q.y - p.y) / len) * 2 * top, y: (p.y + q.y) / 2 + ((q.x - p.x) / len) * 2 * top };
    const toward = (from: { x: number; y: number }, by: number) => {
      const d = Math.hypot(via.x - from.x, via.y - from.y);
      return { x: from.x + ((via.x - from.x) / d) * by, y: from.y + ((via.y - from.y) / d) * by };
    };
    const start = toward(a, R);
    const end = toward(b, view.directed ? R + 2 : R);
    items.push({ key: `edge:${edge.key}`, type: "line", x1: start.x, y1: start.y, x2: end.x, y2: end.y, via, cls, ...tips });
  }
  for (const node of view.nodes) {
    const p = pos.get(node.key)!;
    items.push({ key: `node:${node.key}`, type: "circle", x: p.x, y: p.y, r: R, text: node.text, cls: node.state === "none" ? "" : `rr-${node.state}`, ...(node.sub !== undefined ? { sub: node.sub } : {}) });
  }
  return { items, width: 2 * (radius + R + 20 + extra), height: 2 * (radius + R + extra) + 20 };
}

/** An edge from a node to itself: out from the node, away from the middle, across and back in. */
function selfLoop(key: string, at: { x: number; y: number }, middle: { x: number; y: number }, nth: number, cls: string, tips: { arrow: boolean; text?: string }): Item[] {
  const len = Math.hypot(at.x - middle.x, at.y - middle.y) || 1;
  const ux = (at.x - middle.x) / len || 0;
  const uy = len === 1 ? -1 : (at.y - middle.y) / len; // a lone node in the middle loops upwards
  const reach = R + 20 + nth * 10;
  const side = 8 + nth * 3;
  const point = (out: number, across: number) => ({ x: at.x + ux * out - uy * across, y: at.y + uy * out + ux * across });
  const [start, corner1, corner2, end] = [point(R, -side), point(reach, -side), point(reach, side), point(R + 2, side)];
  return [
    { key: `edge:${key}:out`, type: "line", x1: start.x, y1: start.y, x2: corner1.x, y2: corner1.y, cls },
    { key: `edge:${key}:across`, type: "line", x1: corner1.x, y1: corner1.y, x2: corner2.x, y2: corner2.y, cls, ...(tips.text !== undefined ? { text: tips.text } : {}) },
    { key: `edge:${key}`, type: "line", x1: corner2.x, y1: corner2.y, x2: end.x, y2: end.y, cls, arrow: tips.arrow },
  ];
}

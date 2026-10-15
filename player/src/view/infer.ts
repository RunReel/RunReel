/**
 * Shape inference, first version: decide what to draw for one step from its locals and heap.
 * Arrays, binary trees and weighted graphs are recognised; everything else is left to the
 * variables pane. Views carry stable keys (object ids), so the renderers can animate by id.
 */

import type { HeapObject, State, Value } from "../core/trace";
import { deref, formatValue, isScalar } from "./format";

const POINTER_NAMES = new Set(["i", "j", "k", "l", "r", "lo", "hi", "mid", "left", "right", "low", "high", "start", "end"]);
const CURRENT_NAMES = new Set(["node", "u", "cur", "current", "v", "x"]);
const NEXT_NAMES = new Set(["neighbour", "neighbor", "nbr", "w", "nxt", "next_node"]);

export interface Cell {
  key: string;
  text: string;
  changed: boolean;
}

export interface ArrayView {
  kind: "array";
  key: string;
  label: string;
  cells: Cell[];
  pointers: { name: string; index: number }[];
  more: number;
}

export interface TreeNode {
  key: string;
  text: string;
  left?: string;
  right?: string;
  marks: string[];
}

export interface TreeView {
  kind: "tree";
  key: string;
  label: string;
  root: string;
  nodes: Record<string, TreeNode>;
}

export interface GraphNode {
  key: string;
  text: string;
  sub?: string;
  state: "none" | "visited" | "current" | "next";
}

export interface GraphEdge {
  key: string;
  from: string;
  to: string;
  weight?: string;
  active: boolean;
}

export interface GraphView {
  kind: "graph";
  key: string;
  label: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export type View = ArrayView | TreeView | GraphView;

interface Local {
  name: string;
  value: Value;
}

/** The views for a state, top frame first. prev, the state before it, marks changed cells. */
export function inferViews(state: State, prev?: State): View[] {
  const heap = state.heap;
  const locals = allLocals(state);
  const views: View[] = [];
  const shown = new Set<string>();
  for (const { name, value } of locals) {
    const found = deref(value, heap);
    if (!found) continue;
    const [id, obj] = found;
    if (isTreeNode(obj)) {
      const root = treeRoot(id, heap);
      if (shown.has(`tree:${root}`)) continue;
      shown.add(`tree:${root}`);
      views.push(treeView(root, name, locals, heap));
    } else if (shown.has(id)) {
      continue;
    } else if (isGraph(obj, heap)) {
      shown.add(id);
      views.push(graphView(id, name, obj, locals, heap));
    } else if (isArray(obj, heap)) {
      shown.add(id);
      views.push(arrayView(id, name, obj, state, prev));
    }
  }
  return views;
}

/** Locals of every frame, innermost first, so the running function's names win. */
function allLocals(state: State): Local[] {
  const out: Local[] = [];
  for (const frame of [...state.stack].reverse()) {
    for (const [name, value] of Object.entries(frame.locals)) out.push({ name, value });
  }
  return out;
}

function isArray(obj: HeapObject, heap: Record<string, HeapObject>): boolean {
  if (obj.t !== "seq" || obj.cls === "set" || obj.cls === "frozenset") return false;
  return (obj.items ?? []).every((item) => isScalar(item, heap) || isSmallTuple(item, heap));
}

function isSmallTuple(value: unknown, heap: Record<string, HeapObject>): boolean {
  const found = deref(value, heap);
  return !!found && found[1].t === "seq" && found[1].cls === "tuple" && (found[1].items ?? []).every((v) => isScalar(v, heap));
}

function arrayView(id: string, name: string, obj: HeapObject, state: State, prev?: State): ArrayView {
  const items = obj.items ?? [];
  const before = prev?.heap[id];
  const cells = items.map((item, i) => {
    const text = formatValue(item, state.heap, 1);
    const old = before?.items?.[i];
    const changed = !!before && (i >= (before.items?.length ?? 0) || formatValue(old, prev!.heap, 1) !== text);
    return { key: `${id}:${i}`, text, changed };
  });
  const pointers: { name: string; index: number }[] = [];
  const top = state.stack[state.stack.length - 1];
  for (const [local, value] of Object.entries(top?.locals ?? {})) {
    if (POINTER_NAMES.has(local) && typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= items.length) {
      pointers.push({ name: local, index: value });
    }
  }
  return { kind: "array", key: id, label: name, cells, pointers, more: obj.more ?? 0 };
}

function isTreeNode(obj: HeapObject): boolean {
  return obj.t === "obj" && !!obj.fields && ("left" in obj.fields || "right" in obj.fields);
}

function child(obj: HeapObject | undefined, side: "left" | "right", heap: Record<string, HeapObject>): string | undefined {
  const found = deref(obj?.fields?.[side], heap);
  return found && isTreeNode(found[1]) ? found[0] : undefined;
}

/** The root above a node: the tree node no other tree node points to, following parents up. */
function treeRoot(id: string, heap: Record<string, HeapObject>): string {
  const parent = new Map<string, string>();
  for (const [pid, obj] of Object.entries(heap)) {
    if (!isTreeNode(obj)) continue;
    for (const side of ["left", "right"] as const) {
      const c = child(obj, side, heap);
      if (c) parent.set(c, pid);
    }
  }
  let root = id;
  const seen = new Set([root]);
  for (let up = parent.get(root); up && !seen.has(up); up = parent.get(root)) {
    root = up;
    seen.add(up);
  }
  return root;
}

function treeView(root: string, name: string, locals: Local[], heap: Record<string, HeapObject>): TreeView {
  const nodes: Record<string, TreeNode> = {};
  const marks = new Map<string, string[]>();
  for (const { name: local, value } of locals) {
    const found = deref(value, heap);
    if (found && isTreeNode(found[1])) marks.set(found[0], [...(marks.get(found[0]) ?? []), local]);
  }
  const stack = [root];
  while (stack.length) {
    const id = stack.pop()!;
    if (nodes[id]) continue;
    const obj = heap[id]!;
    const left = child(obj, "left", heap);
    const right = child(obj, "right", heap);
    nodes[id] = { key: id, text: nodeLabel(obj, heap), marks: [...new Set(marks.get(id) ?? [])], ...(left ? { left } : {}), ...(right ? { right } : {}) };
    if (left) stack.push(left);
    if (right) stack.push(right);
  }
  return { kind: "tree", key: `tree:${root}`, label: name, root, nodes };
}

function nodeLabel(obj: HeapObject, heap: Record<string, HeapObject>): string {
  const fields = obj.fields ?? {};
  for (const name of ["key", "val", "value", "data", "item"]) {
    if (name in fields) return formatValue(fields[name], heap, 1);
  }
  const first = Object.entries(fields).find(([k, v]) => k !== "left" && k !== "right" && isScalar(v, heap));
  return first ? formatValue(first[1], heap, 1) : obj.cls;
}

/** A dict mapping each node to a list of neighbours or (neighbour, weight) pairs. */
function isGraph(obj: HeapObject, heap: Record<string, HeapObject>): boolean {
  if (obj.t !== "map" || !obj.items?.length) return false;
  return obj.items.every((pair) => {
    const [key, value] = pair as [Value, Value];
    const list = deref(value, heap);
    return isScalar(key, heap) && !!list && list[1].t === "seq" && (list[1].items ?? []).every((e) => isScalar(e, heap) || isEdgeTuple(e, heap));
  });
}

function isEdgeTuple(value: unknown, heap: Record<string, HeapObject>): boolean {
  const found = deref(value, heap);
  return !!found && found[1].t === "seq" && found[1].items?.length === 2 && isScalar(found[1].items[0], heap);
}

function graphView(id: string, name: string, obj: HeapObject, locals: Local[], heap: Record<string, HeapObject>): GraphView {
  const nodeKey = (v: unknown) => `${id}:${formatValue(v, heap, 1)}`;
  const byName = new Map(locals.map((l) => [l.name, l.value] as const));
  const distName = ["dist", "distance", "dists", "cost"].find((n) => byName.has(n));
  const dist = lookup(distName ? byName.get(distName) : undefined, heap);
  const visited = members(byName.get("visited") ?? byName.get("seen") ?? byName.get("done"), heap);
  const current = [...CURRENT_NAMES].map((n) => byName.get(n)).find((v) => v !== undefined && isScalar(v, heap));
  const next = [...NEXT_NAMES].map((n) => byName.get(n)).find((v) => v !== undefined && isScalar(v, heap));
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  const addNode = (v: unknown) => {
    const key = nodeKey(v);
    if (nodes.has(key)) return key;
    const text = formatValue(v, heap, 1);
    const state = current !== undefined && formatValue(current, heap, 1) === text ? "current" : next !== undefined && formatValue(next, heap, 1) === text ? "next" : visited.has(text) ? "visited" : "none";
    const sub = dist.has(text) ? `${distName}=${dist.get(text)}` : undefined;
    nodes.set(key, { key, text, state, ...(sub !== undefined ? { sub } : {}) });
    return key;
  };
  for (const pair of obj.items ?? []) {
    const [k, list] = pair as [Value, Value];
    const from = addNode(k);
    for (const entry of deref(list, heap)?.[1].items ?? []) {
      const tuple = deref(entry, heap)?.[1].items;
      const to = addNode(tuple ? tuple[0] : entry);
      const weight = tuple ? formatValue(tuple[1], heap, 1) : undefined;
      const active = nodes.get(from)!.state === "current" && nodes.get(to)!.state === "next";
      edges.push({ key: `${from}->${to}`, from, to, active, ...(weight !== undefined ? { weight } : {}) });
    }
  }
  return { kind: "graph", key: id, label: name, nodes: [...nodes.values()], edges };
}

function lookup(value: Value | undefined, heap: Record<string, HeapObject>): Map<string, string> {
  const obj = deref(value, heap)?.[1];
  const out = new Map<string, string>();
  if (obj?.t === "map") for (const pair of obj.items ?? []) {
    const [k, v] = pair as [Value, Value];
    out.set(formatValue(k, heap, 1), formatValue(v, heap, 1));
  }
  return out;
}

function members(value: Value | undefined, heap: Record<string, HeapObject>): Set<string> {
  const obj = deref(value, heap)?.[1];
  const out = new Set<string>();
  if (obj?.t === "seq") for (const item of obj.items ?? []) out.add(formatValue(item, heap, 1));
  if (obj?.t === "map") for (const pair of obj.items ?? []) {
    const [k, v] = pair as [Value, Value];
    if (v !== false && v !== 0 && v !== null) out.add(formatValue(k, heap, 1));
  }
  return out;
}

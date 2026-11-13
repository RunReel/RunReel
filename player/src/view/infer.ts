/**
 * Shape inference, first version: decide what to draw for one step from its locals and heap.
 * Arrays, grids, binary trees, linked lists and weighted graphs are recognised; everything else
 * is left to the variables pane. Views carry stable keys (object ids), so the renderers can
 * animate by id.
 */

import type { HeapObject, State, Value } from "../core/trace";
import { deref, formatValue, isScalar } from "./format";

const POINTER_NAMES = new Set(["i", "j", "k", "l", "r", "lo", "hi", "mid", "left", "right", "low", "high", "start", "end"]);
const CURRENT_NAMES = new Set(["node", "u", "cur", "current", "v", "x"]);
const NEXT_NAMES = new Set(["neighbour", "neighbor", "nbr", "w", "nxt", "next_node"]);
const NEXT_FIELDS = ["next", "_next"]; // a linked list node's link fields
const PREV_FIELDS = ["prev", "_prev"];
// Names for a link pointing back along a list, or up a tree, as a whole word: prev_node, but not upper.
const BACK = /^_*(prev|prv|previous|pred|predecessor|back|backward|bwd|before)($|[_\dA-Z])/;
const UP = /^_*(parent|par|up)($|[_\dA-Z])/;

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
  nth: number; // how many edges from the same node to the same node come before this one
}

export interface GraphView {
  kind: "graph";
  key: string;
  label: string;
  nodes: GraphNode[];
  edges: GraphEdge[]; // an undirected graph lists each edge once
  directed: boolean;
}

export interface GridView {
  kind: "grid";
  key: string;
  label: string;
  rows: Cell[][]; // the cells shown, whose top-left cell is at (top, left)
  top: number;
  left: number;
  height: number; // the whole grid's size, counting any rows or columns not shown
  width: number;
  focus?: { row: number; col: number };
  deps: { row: number; col: number }[]; // cells the current line reads to work out the focus
}

export interface ListNode {
  key: string;
  text: string;
  changed: boolean; // new since the step before, or holding a new value
  relinked: boolean; // its next points somewhere else than it did the step before
  prev?: { to: string | null; relinked: boolean }; // a doubly linked node's prev; null for None
}

/** Where a row's last node points: at a node drawn elsewhere, at None, or on to nodes not shown. */
export type ListEnd = { kind: "node"; to: string } | { kind: "none" } | { kind: "more"; count: number };

export interface ListRow {
  nodes: string[]; // a chain, each node's next the one after it
  skipped: number; // nodes of the chain before the first one shown
  end: ListEnd;
}

export interface ListView {
  kind: "list";
  key: string;
  label: string;
  rows: ListRow[];
  more: number; // chains not drawn
  nodes: Record<string, ListNode>;
  pointers: { name: string; node: string }[];
}

export type View = ArrayView | GridView | TreeView | ListView | GraphView;

const GRID_CELLS = 2500; // a bigger grid shows a window around its focus, this many rows by columns:
const GRID_WINDOW = { rows: 40, cols: 60 };
const LIST_NODES = 30; // a longer chain shows this many nodes, from a few before a pointer:
const LIST_LEAD = 5;
const LIST_ROWS = 10; // chains drawn at most

interface Local {
  name: string;
  value: Value;
}

/**
 * The views for a state. prev, the state before it, marks changed cells, and lines, the
 * program's source, shows which cell of a grid the code is working on. Names come from the
 * running function, but the views are in the order of the outermost frame that has them, so
 * they hold their places as the code calls into a function and returns.
 */
export function inferViews(state: State, prev?: State, lines: readonly string[] = []): View[] {
  const heap = state.heap;
  const locals = allLocals(state);
  const views: View[] = [];
  const shown = new Set<string>();
  for (const { name, value } of locals) {
    const found = deref(value, heap);
    if (!found) continue;
    const [id, obj] = found;
    if (isTreeNode(obj, heap)) {
      const root = treeRoot(id, heap);
      if (shown.has(`tree:${root}`)) continue;
      shown.add(`tree:${root}`);
      views.push(treeView(root, name, locals, heap));
    } else if (isListNode(obj, heap) || listField(obj, heap)) {
      // One view holds every chain, so a list split in two, as reversing one does, stays together.
      if (shown.has("list")) continue;
      shown.add("list");
      views.push(listView(state, prev));
    } else if (shown.has(id)) {
      continue;
    } else if (isGraph(obj, heap)) {
      shown.add(id);
      views.push(graphView(id, name, obj, locals, heap, lines, state.line));
    } else if (gridCells(obj, heap, name, lines)) {
      shown.add(id);
      views.push(gridView(id, name, obj, state, prev, lines, locals));
    } else if (isArray(obj, heap)) {
      shown.add(id);
      views.push(arrayView(id, name, obj, state, prev, lines));
    }
  }
  const place = new Map<string, number>();
  for (const frame of state.stack) {
    for (const value of Object.values(frame.locals)) {
      const key = viewKey(value, heap);
      if (key !== undefined && !place.has(key)) place.set(key, place.size);
    }
  }
  return views.sort((a, b) => (place.get(a.key) ?? 0) - (place.get(b.key) ?? 0));
}

/** The key of the view a variable's value would be drawn in, if any. */
function viewKey(value: Value, heap: Record<string, HeapObject>): string | undefined {
  const found = deref(value, heap);
  if (!found) return undefined;
  if (isTreeNode(found[1], heap)) return `tree:${treeRoot(found[0], heap)}`;
  if (isListNode(found[1], heap) || listField(found[1], heap)) return "list";
  return found[0];
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

function arrayView(id: string, name: string, obj: HeapObject, state: State, prev: State | undefined, lines: readonly string[]): ArrayView {
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
    if (typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= items.length && points(local, name, lines)) {
      pointers.push({ name: local, index: value });
    }
  }
  return { kind: "array", key: id, label: name, cells, pointers, more: obj.more ?? 0 };
}

/**
 * Whether the number local is drawn as a pointer under the array name: if the code indexes the
 * array with it anywhere, as in name[local], name[local + 1] or name[lo:hi]; or if it's one of
 * the usual names, lo or hi say, that indexes nothing itself, and the code indexes this array.
 * So a list the code only appends to gets no stray i. Without the source, the usual names count.
 */
function points(local: string, name: string, lines: readonly string[]): boolean {
  if (!lines.length) return POINTER_NAMES.has(local);
  const subs = subscripts(lines);
  const own = subs.names.get(name);
  return !!own && (own.has(local) || (POINTER_NAMES.has(local) && !subs.all.has(local)));
}

const SUBSCRIPTS = new WeakMap<readonly string[], { names: Map<string, Set<string>>; all: Set<string> }>();

/**
 * For each name the source subscripts, the names inside its brackets: i in a[i + 1], lo and hi
 * in a[lo:hi], i and j in a[min(i, j)], but not i in a[b[i]], which is b's, nor calls such as
 * len or attributes. all is every name used in any subscript.
 */
function subscripts(lines: readonly string[]): { names: Map<string, Set<string>>; all: Set<string> } {
  const cached = SUBSCRIPTS.get(lines);
  if (cached) return cached;
  const names = new Map<string, Set<string>>();
  const all = new Set<string>();
  for (const line of lines) {
    for (const m of line.matchAll(/(?<![\w.])([A-Za-z_]\w*)\s*\[/g)) {
      let inner = "";
      let depth = 0;
      for (const ch of line.slice(m.index! + m[0].length)) {
        if (ch === "]" && depth === 0) break;
        if (ch === "[") depth++;
        if (ch === "]") depth--;
        inner += depth === 0 && ch !== "]" ? ch : " ";
      }
      const used = names.get(m[1]!) ?? new Set<string>();
      for (const id of inner.matchAll(/(?<![\w.])([A-Za-z_]\w*)\b(?!\s*\()/g)) {
        used.add(id[1]!);
        all.add(id[1]!);
      }
      names.set(m[1]!, used);
    }
  }
  const found = { names, all };
  SUBSCRIPTS.set(lines, found);
  return found;
}

/**
 * The cells of a grid as text, row by row: a list of equal-length lists of plain values, or of
 * equal-length strings if the code indexes it as name[r][c] (else a list of words would count).
 * Rows of tuples don't count: a list of (dist, node) pairs reads better as an array of pairs.
 */
function gridCells(obj: HeapObject, heap: Record<string, HeapObject>, name: string, lines: readonly string[]): { cells: string[][]; height: number; width: number } | undefined {
  if (obj.t !== "seq" || obj.cls === "set" || obj.cls === "frozenset" || !obj.items?.length) return undefined;
  const strings = obj.items.every((item) => typeof item === "string");
  if (strings && (obj.items.length < 2 || !lines.some((line) => gridIndexes(name, line).length))) return undefined;
  const cells: string[][] = [];
  let width = -1;
  for (const item of obj.items) {
    let row: string[];
    let size: number;
    if (strings) {
      row = [...(item as string)];
      size = row.length;
    } else {
      const found = deref(item, heap)?.[1];
      if (!found || found.t !== "seq" || found.cls !== "list") return undefined;
      const items = found.items ?? [];
      if (!items.every((v) => isScalar(v, heap))) return undefined;
      row = items.map((v) => formatValue(v, heap));
      size = items.length + (found.more ?? 0);
    }
    if (size === 0 || (width !== -1 && size !== width)) return undefined;
    width = size;
    cells.push(row);
  }
  return { cells, height: obj.items.length + (obj.more ?? 0), width };
}

interface GridIndex {
  row: string;
  rowShift: number;
  col: string;
  colShift: number;
}

/** Every name[a][b] in a line, where a and b are names with an optional + or - a number. */
function gridIndexes(name: string, line: string): GridIndex[] {
  const part = String.raw`\[\s*([A-Za-z_]\w*)\s*(?:([+-])\s*(\d+)\s*)?\]`;
  const found: GridIndex[] = [];
  for (const m of line.matchAll(new RegExp(String.raw`(?<![\w.])${name}\s*${part}\s*${part}`, "g"))) {
    const shift = (sign?: string, n?: string) => (sign === "-" ? -1 : 1) * Number(n ?? 0);
    found.push({ row: m[1]!, rowShift: shift(m[2], m[3]), col: m[4]!, colShift: shift(m[5], m[6]) });
  }
  return found;
}

function gridView(id: string, name: string, obj: HeapObject, state: State, prev: State | undefined, lines: readonly string[], locals: Local[]): GridView {
  const { cells, height, width } = gridCells(obj, state.heap, name, lines)!;
  const before = prev?.heap[id] ? gridCells(prev.heap[id]!, prev.heap, name, lines)?.cells : undefined;
  const { focus, deps } = gridFocus(name, state, lines, locals, cells.length, cells[0]!.length);
  let top = 0;
  let left = 0;
  let rows = cells.length;
  let cols = cells[0]!.length;
  if (rows * cols > GRID_CELLS) {
    rows = Math.min(rows, GRID_WINDOW.rows);
    cols = Math.min(cols, GRID_WINDOW.cols);
    const centre = (at: number | undefined, size: number, all: number) => Math.min(Math.max((at ?? 0) - Math.floor(size / 2), 0), all - size);
    top = centre(focus?.row, rows, cells.length);
    left = centre(focus?.col, cols, cells[0]!.length);
  }
  const shown = cells.slice(top, top + rows).map((row, r) =>
    row.slice(left, left + cols).map((text, c) => {
      const old = before?.[top + r]?.[left + c];
      return { key: `${id}:${top + r}:${left + c}`, text, changed: before !== undefined && old !== text };
    }),
  );
  return { kind: "grid", key: id, label: name, rows: shown, top, left, height, width, ...(focus ? { focus } : {}), deps };
}

/**
 * The cell the code is working on, and the cells it reads to work it out: from name[a][b] on
 * the current line, or else the a and b the program indexes the grid with most often.
 */
function gridFocus(name: string, state: State, lines: readonly string[], locals: Local[], rows: number, cols: number): Pick<GridView, "focus" | "deps"> {
  const number = (local: string) => {
    const value = locals.find((l) => l.name === local)?.value;
    return typeof value === "number" && Number.isInteger(value) ? value : undefined;
  };
  const cell = (ix: GridIndex) => {
    const row = number(ix.row);
    const col = number(ix.col);
    if (row === undefined || col === undefined) return undefined;
    const at = { row: row + ix.rowShift, col: col + ix.colShift };
    return at.row >= 0 && at.row < rows && at.col >= 0 && at.col < cols ? at : undefined;
  };
  const here = gridIndexes(name, lines[state.line - 1] ?? "");
  const plain = here.find((ix) => !ix.rowShift && !ix.colShift);
  const focus = (plain && cell(plain)) ?? here.map(cell).find((c) => c !== undefined) ?? usualCell(name, lines, cell);
  if (!focus) return { deps: [] };
  const deps: { row: number; col: number }[] = [];
  for (const at of here.map(cell)) {
    if (at && (at.row !== focus.row || at.col !== focus.col) && !deps.some((d) => d.row === at.row && d.col === at.col)) deps.push(at);
  }
  return { focus, deps };
}

/** The cell named by the plain name[a][b] the program uses most for this grid, if any. */
function usualCell(name: string, lines: readonly string[], cell: (ix: GridIndex) => { row: number; col: number } | undefined) {
  const counts = new Map<string, [number, GridIndex]>();
  for (const line of lines) {
    for (const ix of gridIndexes(name, line)) {
      if (ix.rowShift || ix.colShift) continue;
      const key = `${ix.row},${ix.col}`;
      counts.set(key, [(counts.get(key)?.[0] ?? 0) + 1, ix]);
    }
  }
  const best = [...counts.values()].sort((a, b) => b[0] - a[0])[0];
  return best ? cell(best[1]) : undefined;
}

/** How a node links to others: a tree's left and right fields, or a list's next and prev. */
type Links = { kind: "tree"; left?: string; right?: string } | { kind: "list"; next: string; prev?: string };

/**
 * How obj links to other nodes, if it is one: by the usual field names first, left and right
 * for a tree and next and prev for a list, so a lone node shows before anything links to it,
 * and otherwise by how the objects of its class point at each other, whatever the fields are called.
 */
function links(obj: HeapObject, heap: Record<string, HeapObject>): Links | undefined {
  if (obj.t !== "obj") return undefined;
  const fields = obj.fields ?? {};
  if ("left" in fields || "right" in fields) return { kind: "tree", left: "left", right: "right" };
  const next = linkName(obj, NEXT_FIELDS);
  if (next !== undefined) {
    const prev = linkName(obj, PREV_FIELDS);
    return { kind: "list", next, ...(prev !== undefined ? { prev } : {}) };
  }
  return classLinks(heap).get(obj.cls);
}

const CLASS_LINKS = new WeakMap<Record<string, HeapObject>, Map<string, Links>>();

/** How the objects of each class in the heap link to each other, worked out once per heap. */
function classLinks(heap: Record<string, HeapObject>): Map<string, Links> {
  let shapes = CLASS_LINKS.get(heap);
  if (shapes) return shapes;
  shapes = new Map();
  const byClass = new Map<string, [string, HeapObject][]>();
  for (const [id, obj] of Object.entries(heap)) {
    if (obj.t !== "obj") continue;
    const same = byClass.get(obj.cls);
    if (same) same.push([id, obj]);
    else byClass.set(obj.cls, [[id, obj]]);
  }
  for (const [cls, objs] of byClass) {
    const shape = classShape(cls, objs, heap);
    if (shape) shapes.set(cls, shape);
  }
  CLASS_LINKS.set(heap, shapes);
  return shapes;
}

/**
 * A class's shape, from its link fields: those holding None or an object of the same class in
 * every object of the class, and such an object in at least one. One link makes a linked list,
 * unless it's called parent or up, as in a forest, which isn't drawn yet.
 * Two make a doubly linked list if they point back at each other anywhere, and a binary tree if
 * they never do, or if one is called parent or up, as a tree with one child so far has. Of three,
 * one pointing back at both others, as a parent does, is left out. The way each link points comes
 * from its name if that says (prev, back, l and r), else from the order the fields were set in.
 */
function classShape(cls: string, objs: [string, HeapObject][], heap: Record<string, HeapObject>): Links | undefined {
  const names = [...new Set(objs.flatMap(([, obj]) => Object.keys(obj.fields ?? {})))];
  const target = (obj: HeapObject, field: string) => deref(obj.fields?.[field], heap);
  let fields = names.filter((field) => {
    let linked = false;
    for (const [, obj] of objs) {
      const value = obj.fields?.[field];
      if (value === undefined || value === null) continue;
      const found = target(obj, field);
      if (!found || found[1].cls !== cls) return false;
      if (found[1].t === "obj") linked = true; // a placeholder for an object past the limit says nothing either way
    }
    return linked;
  });
  const backAndForth = (a: string, b: string) =>
    objs.some(([id, obj]) => {
      const to = target(obj, a);
      return !!to && to[0] !== id && deref(to[1].fields?.[b], heap)?.[0] === id;
    });
  if (fields.length === 3) {
    const up = fields.find((f) => fields.every((g) => g === f || backAndForth(f, g) || backAndForth(g, f)));
    const rest = fields.filter((f) => f !== up);
    if (!up || backAndForth(rest[0]!, rest[1]!) || backAndForth(rest[1]!, rest[0]!)) return undefined;
    fields = rest;
  }
  if (fields.length === 1) return UP.test(fields[0]!) ? undefined : { kind: "list", next: fields[0]! }; // parents alone make a forest
  if (fields.length !== 2) return undefined;
  const [a, b] = fields as [string, string];
  const rightward = (f: string) => /^_*r/i.test(f);
  if (backAndForth(a, b) || backAndForth(b, a)) {
    const down = UP.test(b) ? a : UP.test(a) ? b : undefined;
    if (down !== undefined) return rightward(down) ? { kind: "tree", right: down } : { kind: "tree", left: down };
    const [next, prev] = BACK.test(a) && !BACK.test(b) ? [b, a] : [a, b];
    return { kind: "list", next, prev };
  }
  const [left, right] = rightward(a) && /^_*l/i.test(b) ? [b, a] : [a, b];
  return { kind: "tree", left, right };
}

function isTreeNode(obj: HeapObject, heap: Record<string, HeapObject>): boolean {
  return links(obj, heap)?.kind === "tree";
}

function child(obj: HeapObject | undefined, side: "left" | "right", heap: Record<string, HeapObject>): string | undefined {
  const shape = obj && links(obj, heap);
  const field = shape?.kind === "tree" ? shape[side] : undefined;
  if (field === undefined) return undefined;
  const found = deref(obj!.fields?.[field], heap);
  return found && isTreeNode(found[1], heap) ? found[0] : undefined;
}

/** The root above a node: the tree node no other tree node points to, following parents up. */
function treeRoot(id: string, heap: Record<string, HeapObject>): string {
  const parent = new Map<string, string>();
  for (const [pid, obj] of Object.entries(heap)) {
    if (!isTreeNode(obj, heap)) continue;
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
    if (found && isTreeNode(found[1], heap)) marks.set(found[0], [...(marks.get(found[0]) ?? []), local]);
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
  const shape = links(obj, heap);
  const own = shape?.kind === "tree" ? [shape.left, shape.right] : shape ? [shape.next, shape.prev] : [];
  const skip = ["left", "right", ...NEXT_FIELDS, ...PREV_FIELDS, ...own];
  const first = Object.entries(fields).find(([k, v]) => !skip.includes(k) && isScalar(v, heap));
  return first ? formatValue(first[1], heap, 1) : obj.cls;
}

function isListNode(obj: HeapObject, heap: Record<string, HeapObject>): boolean {
  return links(obj, heap)?.kind === "list";
}

/** Which of names is obj's link field: the first it has that holds None or a reference. */
function linkName(obj: HeapObject, names: readonly string[]): string | undefined {
  const fields = obj.fields ?? {};
  return names.find((name) => {
    const value = fields[name];
    return value === null || (typeof value === "object" && "ref" in value);
  });
}

/** The node a list node's next or prev points at: its id, null for None, or undefined if it isn't a list node. */
function linkTarget(obj: HeapObject, which: "next" | "prev", heap: Record<string, HeapObject>): string | null | undefined {
  const shape = links(obj, heap);
  const field = shape?.kind === "list" ? shape[which] : undefined;
  const value = field === undefined ? undefined : obj.fields?.[field];
  if (value === undefined) return undefined;
  if (value === null) return null;
  const found = deref(value, heap);
  return found && isListNode(found[1], heap) ? found[0] : undefined;
}

/** The field of an object, not itself a node, that holds a list node: a LinkedList's head, say. */
function listField(obj: HeapObject, heap: Record<string, HeapObject>): string | undefined {
  if (obj.t !== "obj" || links(obj, heap)) return undefined;
  return Object.keys(obj.fields ?? {}).find((field) => {
    const found = deref(obj.fields![field], heap);
    return !!found && isListNode(found[1], heap);
  });
}

/**
 * Every list node in the heap, each chain on a row of its own in next order: the chains start at
 * the nodes nothing points at, oldest first, then go round any loops left with no way in. The
 * rows come in order of their oldest node, which keeps them in place as nodes move between them.
 */
function listView(state: State, prev: State | undefined): ListView {
  const heap = state.heap;
  const nexts = new Map<string, string | null | undefined>();
  for (const [id, obj] of Object.entries(heap)) if (isListNode(obj, heap)) nexts.set(id, linkTarget(obj, "next", heap));
  const pointedAt = new Set([...nexts.values()].filter((to): to is string => typeof to === "string"));
  const placed = new Set<string>();
  const chains: { nodes: string[]; end: string | null | undefined; oldest: number }[] = [];
  const walk = (start: string) => {
    const nodes: string[] = [];
    let at: string | null | undefined = start;
    while (typeof at === "string" && !placed.has(at)) {
      placed.add(at);
      nodes.push(at);
      at = nexts.get(at);
    }
    chains.push({ nodes, end: at, oldest: Math.min(...nodes.map(Number)) });
  };
  for (const id of nexts.keys()) if (!pointedAt.has(id)) walk(id);
  for (const id of nexts.keys()) if (!placed.has(id)) walk(id);
  chains.sort((a, b) => a.oldest - b.oldest);

  const top = state.stack[state.stack.length - 1];
  const pointers = listPointers(top?.locals ?? {}, heap);
  const marked = pointers.map((p) => p.node);
  const nodes: Record<string, ListNode> = {};
  const rows = chains.slice(0, LIST_ROWS).map((chain): ListRow => {
    const start = windowStart(chain.nodes, marked);
    const shown = chain.nodes.slice(start, start + LIST_NODES);
    for (const id of shown) nodes[id] = listNode(id, heap, prev);
    const after = chain.nodes.length - start - shown.length;
    const end: ListEnd =
      after > 0 ? { kind: "more", count: after } : chain.end === null ? { kind: "none" } : chain.end === undefined ? { kind: "more", count: 0 } : { kind: "node", to: chain.end };
    return { nodes: shown, skipped: start, end };
  });
  return { kind: "list", key: "list", label: listLabel(state), rows, more: chains.length - rows.length, nodes, pointers: pointers.filter((p) => nodes[p.node]) };
}

/**
 * Where to start showing a chain too long to show whole: the stretch with the most pointers in
 * it, and of those the furthest along, since the code usually walks a pointer forwards.
 */
function windowStart(chain: string[], marked: string[]): number {
  if (chain.length <= LIST_NODES) return 0;
  const at = marked.map((id) => chain.indexOf(id)).filter((i) => i >= 0);
  let best = 0;
  let most = -1;
  for (const start of [0, ...at.map((i) => Math.min(Math.max(i - LIST_LEAD, 0), chain.length - LIST_NODES))]) {
    const count = at.filter((i) => i >= start && i < start + LIST_NODES).length;
    if (count > most || (count === most && start > best)) [best, most] = [start, count];
  }
  return best;
}

/** The first name for a list node in the outermost frame that has one, so the title holds still
 * while the code steps into a node's constructor or a helper. */
function listLabel(state: State): string {
  for (const frame of state.stack) {
    for (const [name, value] of Object.entries(frame.locals)) {
      const found = deref(value, state.heap);
      if (!found) continue;
      if (isListNode(found[1], state.heap)) return name;
      const field = listField(found[1], state.heap);
      if (field) return `${name}.${field}`;
    }
  }
  return "list";
}

function listNode(id: string, heap: Record<string, HeapObject>, prev: State | undefined): ListNode {
  const obj = heap[id]!;
  const text = nodeLabel(obj, heap);
  const old = prev?.heap[id];
  const was = old && isListNode(old, prev!.heap) ? old : undefined;
  const node: ListNode = {
    key: id,
    text,
    changed: !!prev && (!was || nodeLabel(was, prev.heap) !== text),
    relinked: !!was && linkTarget(was, "next", prev!.heap) !== linkTarget(obj, "next", heap),
  };
  const back = linkTarget(obj, "prev", heap);
  if (back !== undefined) node.prev = { to: back, relinked: !!was && linkTarget(was, "prev", prev!.heap) !== back };
  return node;
}

/** The running function's locals that point at a list node, and fields of its objects that do, as self.head. */
function listPointers(locals: Record<string, Value>, heap: Record<string, HeapObject>): { name: string; node: string }[] {
  const out: { name: string; node: string }[] = [];
  for (const [name, value] of Object.entries(locals)) {
    const found = deref(value, heap);
    if (!found) continue;
    if (isListNode(found[1], heap)) {
      out.push({ name, node: found[0] });
    } else if (found[1].t === "obj") {
      for (const [field, inner] of Object.entries(found[1].fields ?? {})) {
        const node = deref(inner, heap);
        if (node && isListNode(node[1], heap)) out.push({ name: `${name}.${field}`, node: node[0] });
      }
    }
  }
  return out;
}

type Adjacency = [node: Value, edges: [to: Value, weight: Value | undefined][]][];

/**
 * A graph's nodes and edges, if obj is one: a dict mapping each node to a list (or set) of
 * neighbours or (neighbour, weight) pairs, or to a dict from neighbour to weight. Its lists have
 * to name its own keys somewhere, so a dict like {"fruit": ["apple", "pear"]} isn't a graph.
 */
function adjacency(obj: HeapObject, heap: Record<string, HeapObject>): Adjacency | undefined {
  if (obj.t !== "map" || !obj.items?.length) return undefined;
  const graph: Adjacency = [];
  for (const pair of obj.items) {
    const [node, value] = pair as [Value, Value];
    const inner = deref(value, heap)?.[1];
    if (!isScalar(node, heap) || !inner) return undefined;
    const edges: [Value, Value | undefined][] = [];
    if (inner.t === "seq") {
      for (const entry of inner.items ?? []) {
        if (isScalar(entry, heap)) edges.push([entry as Value, undefined]);
        else if (isEdgeTuple(entry, heap)) edges.push(deref(entry, heap)![1].items as [Value, Value]);
        else return undefined;
      }
    } else if (inner.t === "map") {
      for (const entry of inner.items ?? []) {
        const [to, weight] = entry as [Value, Value];
        if (!isScalar(to, heap) || !isScalar(weight, heap)) return undefined;
        edges.push([to, weight]);
      }
    } else {
      return undefined;
    }
    graph.push([node, edges]);
  }
  const keys = new Set(graph.map(([node]) => formatValue(node, heap, 1)));
  return graph.some(([, edges]) => edges.some(([to]) => keys.has(formatValue(to, heap, 1)))) ? graph : undefined;
}

function isGraph(obj: HeapObject, heap: Record<string, HeapObject>): boolean {
  return adjacency(obj, heap) !== undefined;
}

function isEdgeTuple(value: unknown, heap: Record<string, HeapObject>): boolean {
  const found = deref(value, heap);
  return !!found && found[1].t === "seq" && found[1].items?.length === 2 && isScalar(found[1].items[0], heap);
}

/**
 * How the code walks the graph called name: the node being processed is what it indexes the
 * graph with, as u in name[u], and the neighbour is what it loops over, as v in
 * `for v in name[u]` or `for v, w in name[u].items()`. Names used nearer the running line come
 * first, so the main loop's u wins over a counting loop's leftover n.
 */
function graphRoles(name: string, lines: readonly string[], at: number): { current: string[]; next: string[] } {
  const used = new Map<string, number>(); // name -> distance from the running line to its nearest use
  const next = new Set<string>();
  const loop = new RegExp(String.raw`\bfor\s+\(?\s*([A-Za-z_]\w*)[^:]*?\bin\s+${name}\s*(\[|\.get\()`);
  lines.forEach((line, i) => {
    const near = (n: string) => used.set(n, Math.min(used.get(n) ?? Infinity, Math.abs(i + 1 - at)));
    const m = loop.exec(line);
    if (m) {
      next.add(m[1]!);
      near(m[1]!);
    }
    for (const n of subscripts([line]).names.get(name) ?? []) near(n);
  });
  const byNearness = (names: string[]) => names.sort((a, b) => used.get(a)! - used.get(b)!);
  const current = byNearness([...(subscripts(lines).names.get(name) ?? [])].filter((n) => !next.has(n)));
  return { current, next: byNearness([...next]) };
}

const DIST_NAMES = ["dist", "distance", "dists", "cost"];
const VISITED_NAMES = ["visited", "seen", "done"];

function graphView(id: string, name: string, obj: HeapObject, locals: Local[], heap: Record<string, HeapObject>, lines: readonly string[], at: number): GraphView {
  const graph = adjacency(obj, heap)!;
  const text = (v: unknown) => formatValue(v, heap, 1);
  const nodeKey = (v: unknown) => `${id}:${text(v)}`;
  const texts = new Set(graph.flatMap(([node, edges]) => [text(node), ...edges.map(([to]) => text(to))]));
  // Locals are innermost first, so the running function's own u wins over a caller's.
  const value = (local: string) => locals.find((l) => l.name === local)?.value;
  const isNode = (v: Value | undefined) => v !== undefined && v !== null && isScalar(v, heap) && texts.has(text(v));
  const roles = graphRoles(name, lines, at);
  const current = [...roles.current, ...CURRENT_NAMES].map(value).find(isNode);
  const next = [...roles.next, ...NEXT_NAMES].map(value).find(isNode);
  const marks = graphMarks(name, locals, heap, lines, texts, [...roles.current, ...roles.next]);
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];
  const addNode = (v: unknown) => {
    const key = nodeKey(v);
    if (nodes.has(key)) return key;
    const t = text(v);
    const state = current !== undefined && text(current) === t ? "current" : next !== undefined && text(next) === t ? "next" : marks.visited.has(t) ? "visited" : "none";
    const sub = marks.values.get(t);
    nodes.set(key, { key, text: t, state, ...(sub !== undefined ? { sub: `${marks.label}=${sub}` } : {}) });
    return key;
  };
  for (const [node, list] of graph) {
    const from = addNode(node);
    for (const [entry, weight] of list) {
      const to = addNode(entry);
      const active = nodes.get(from)!.state === "current" && nodes.get(to)!.state === "next";
      const nth = edges.filter((e) => e.from === from && e.to === to).length;
      edges.push({ key: nth ? `${from}->${to}#${nth}` : `${from}->${to}`, from, to, active, nth, ...(weight !== undefined ? { weight: text(weight) } : {}) });
    }
  }
  const directed = !isSymmetric(edges);
  if (directed) return { kind: "graph", key: id, label: name, nodes: [...nodes.values()], edges, directed };
  // Undirected: each edge is listed both ways, so keep the copy from the node listed first, and
  // let it light up when the code walks it either way.
  const order = [...nodes.keys()];
  const once = edges
    .filter((e) => order.indexOf(e.from) <= order.indexOf(e.to))
    .map((e) => ({ ...e, active: e.active || edges.some((r) => r.from === e.to && r.to === e.from && r.nth === e.nth && r.active) }));
  return { kind: "graph", key: id, label: name, nodes: [...nodes.values()], edges: once, directed };
}

/** Whether every edge has a twin going back with the same weight, as an undirected graph stored as a dict has. */
function isSymmetric(edges: GraphEdge[]): boolean {
  const count = new Map<string, number>();
  const bump = (from: string, to: string, weight: string | undefined, by: number) => {
    const key = JSON.stringify([from, to, weight ?? null]);
    count.set(key, (count.get(key) ?? 0) + by);
  };
  for (const e of edges) {
    if (e.from === e.to) continue;
    bump(e.from, e.to, e.weight, 1);
    bump(e.to, e.from, e.weight, -1);
  }
  return count.size > 0 && [...count.values()].every((n) => n === 0);
}

/**
 * What to write under each node and which nodes count as visited. Usual names come first:
 * dist or cost for the values, visited or seen for the visited nodes. Otherwise the values come
 * from a dict or list the code indexes with the node variables, as indegree[v] or parent[v],
 * and visited from a set of nodes or a list of True and False indexed by node.
 */
function graphMarks(name: string, locals: Local[], heap: Record<string, HeapObject>, lines: readonly string[], nodes: Set<string>, roles: string[]) {
  const seen = new Set<string>();
  const own = locals.filter((l) => l.name !== name && !seen.has(l.name) && seen.add(l.name));
  const indexedByNode = (local: string) => roles.some((r) => subscripts(lines).names.get(local)?.has(r));
  let label = "";
  let values = new Map<string, string>();
  let visited = new Set<string>();
  for (const { name: local, value } of [...own.filter((l) => DIST_NAMES.includes(l.name)), ...own]) {
    const found = byNode(value, heap, nodes);
    if (!found || found.bools || !(DIST_NAMES.includes(local) || indexedByNode(local))) continue;
    [label, values] = [local, found.values];
    break;
  }
  for (const { name: local, value } of [...own.filter((l) => VISITED_NAMES.includes(l.name)), ...own]) {
    const obj = deref(value, heap)?.[1];
    if (obj?.t === "seq" && (obj.cls === "set" || obj.cls === "frozenset") && (VISITED_NAMES.includes(local) || (obj.items?.length && obj.items.every((i) => nodes.has(nodeText(i, heap)))))) {
      visited = new Set((obj.items ?? []).map((i) => nodeText(i, heap)));
      break;
    }
    const found = byNode(value, heap, nodes);
    if (found && (found.bools || VISITED_NAMES.includes(local)) && (VISITED_NAMES.includes(local) || indexedByNode(local))) {
      visited = new Set([...found.values].filter(([, v]) => v !== "False" && v !== "0" && v !== "None").map(([k]) => k));
      break;
    }
  }
  return { label, values, visited };
}

const nodeText = (v: unknown, heap: Record<string, HeapObject>) => formatValue(v, heap, 1);

/** A dict keyed by nodes, or a list indexed by them, as node text to value text; bools says whether every value is True or False. */
function byNode(value: Value | undefined, heap: Record<string, HeapObject>, nodes: Set<string>): { values: Map<string, string>; bools: boolean } | undefined {
  const obj = deref(value, heap)?.[1];
  const values = new Map<string, string>();
  let bools = true;
  const add = (k: string, v: unknown) => {
    if (!isScalar(v, heap)) return false;
    values.set(k, nodeText(v, heap));
    bools &&= typeof v === "boolean";
    return true;
  };
  if (obj?.t === "map") {
    for (const pair of obj.items ?? []) {
      const [k, v] = pair as [Value, Value];
      if (!nodes.has(nodeText(k, heap)) || !add(nodeText(k, heap), v)) return undefined;
    }
  } else if (obj?.t === "seq" && obj.cls === "list") {
    if (!(obj.items ?? []).every((v, i) => add(String(i), v))) return undefined;
  } else {
    return undefined;
  }
  return values.size && [...values.keys()].some((k) => nodes.has(k)) ? { values, bools } : undefined;
}

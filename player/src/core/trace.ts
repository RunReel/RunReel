/**
 * Trace format v1 on the player side: the types plus a decoder that rebuilds any step.
 * A keyframe is a delta from the empty state, so one function, applyStep, decodes both.
 * The formal definition is schema/trace-v1.schema.json.
 */

export type Value =
  | null
  | boolean
  | number
  | string
  | { ref: number }
  | { inf: 1 | -1 }
  | { nan: 1 }
  | { bigint: string };

export type Event = "call" | "line" | "return" | "exception";

/** An object that variables refer to. Which fields are present depends on t. */
export interface HeapObject {
  t: "seq" | "map" | "obj" | "repr";
  cls: string;
  items?: unknown[]; // seq: values; map: [key, value] pairs
  more?: number; // items left out beyond the size cap
  fields?: Record<string, Value>; // obj only
  v?: string; // repr only
}

/** One edit to items: replace the item at index, or remove count items at start and insert items. */
export type Op = [index: number, item: unknown] | [start: number, count: number, items: unknown[]];

/**
 * Changes to an object that keeps its t and cls. ops edit a seq's or map's items, using the
 * indices from before the patch; set and del edit an obj's fields; more replaces the count of
 * items left out (0 removes it).
 */
export interface ObjectPatch {
  ops?: Op[];
  set?: Record<string, Value>;
  del?: string[];
  more?: number;
}

export interface FramePatch {
  fn?: string;
  line?: number;
  set?: Record<string, Value>;
  del?: string[];
}

/** What one step changed. */
export interface Step {
  ev: Event;
  line: number;
  key?: true;
  stack?: number[];
  frames?: Record<string, FramePatch>;
  heap?: Record<string, HeapObject | ObjectPatch>;
  gc?: number[];
  ret?: Value;
  exc?: string;
}

export interface Frame {
  fid: number;
  fn: string;
  line: number;
  locals: Record<string, Value>;
}

/** The full program state after one step. */
export interface State {
  ev: Event;
  line: number;
  stack: Frame[];
  heap: Record<string, HeapObject>;
  ret?: Value;
  exc?: string;
}

export function emptyState(): State {
  return { ev: "line", line: 0, stack: [], heap: {} };
}

/** Rebuild the state after step n by replaying from the nearest keyframe at or before it. */
export function stateAt(steps: readonly Step[], n: number): State {
  if (!Number.isInteger(n) || n < 0 || n >= steps.length) {
    throw new RangeError(`step ${n} is out of range for ${steps.length} steps`);
  }
  let k = n;
  while (!steps[k]?.key) {
    if (k === 0) throw new Error("the first step must be a keyframe");
    k -= 1;
  }
  const state = emptyState();
  for (const step of steps.slice(k, n + 1)) applyStep(state, step);
  return state;
}

/** Apply one step to state in place. Used by stateAt and for playing forward. */
export function applyStep(state: State, step: Step): void {
  if (step.key) {
    state.stack = [];
    state.heap = {};
  }
  state.ev = step.ev;
  state.line = step.line;
  delete state.ret;
  delete state.exc;
  if (step.stack) {
    const byFid = new Map(state.stack.map((frame) => [frame.fid, frame]));
    state.stack = step.stack.map((fid) => byFid.get(fid) ?? { fid, fn: "", line: 0, locals: {} });
  }
  const top = state.stack[state.stack.length - 1];
  if (top) top.line = step.line;
  const byFid = new Map(state.stack.map((frame) => [frame.fid, frame]));
  for (const [fid, patch] of Object.entries(step.frames ?? {})) {
    const frame = byFid.get(Number(fid));
    if (!frame) throw new Error(`frame ${fid} is not on the stack`);
    if (patch.fn !== undefined) frame.fn = patch.fn;
    if (patch.line !== undefined) frame.line = patch.line;
    Object.assign(frame.locals, patch.set);
    for (const name of patch.del ?? []) delete frame.locals[name];
  }
  for (const [id, entry] of Object.entries(step.heap ?? {})) {
    if ("t" in entry) state.heap[id] = copyObject(entry);
    else applyPatch(state.heap[id], entry);
  }
  for (const id of step.gc ?? []) delete state.heap[String(id)];
  if (step.ret !== undefined) state.ret = step.ret;
  if (step.exc !== undefined) state.exc = step.exc;
}

/** Edit an object in place. Ops index the items as they were, so they run back to front. */
function applyPatch(obj: HeapObject | undefined, patch: ObjectPatch): void {
  if (!obj) throw new Error("a patch needs an existing object");
  if (patch.ops) {
    const items = obj.items;
    if (!items) throw new Error("ops need a seq or map");
    for (const op of patch.ops.slice().reverse()) {
      if (op.length === 2) items[op[0]] = op[1];
      else items.splice(op[0], op[1], ...op[2]);
    }
  }
  if (patch.set || patch.del) {
    if (!obj.fields) throw new Error("set and del need an obj");
    // Spread, not Object.assign, so a field named __proto__ stays an ordinary field.
    const fields = { ...obj.fields, ...patch.set };
    for (const name of patch.del ?? []) delete fields[name];
    obj.fields = fields;
  }
  if (patch.more !== undefined) {
    if (patch.more > 0) obj.more = patch.more;
    else delete obj.more;
  }
}

/** A copy whose items or fields can be patched without changing the trace itself. */
function copyObject(obj: HeapObject): HeapObject {
  const copy: HeapObject = { ...obj };
  if (obj.items) copy.items = obj.items.slice();
  if (obj.fields) copy.fields = { ...obj.fields };
  return copy;
}

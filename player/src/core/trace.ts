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

/** Changes to a seq or map: resize to len, overwrite [index, item] entries, set more. */
export interface ItemPatch {
  len?: number;
  set?: [number, unknown][];
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
  heap?: Record<string, HeapObject | ItemPatch>;
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
    else applyItemPatch(state.heap[id], entry);
  }
  for (const id of step.gc ?? []) delete state.heap[String(id)];
  if (step.ret !== undefined) state.ret = step.ret;
  if (step.exc !== undefined) state.exc = step.exc;
}

function applyItemPatch(obj: HeapObject | undefined, patch: ItemPatch): void {
  const items = obj?.items;
  if (!obj || !items) throw new Error("an item patch needs an existing seq or map");
  if (patch.len !== undefined) {
    items.length = Math.min(items.length, patch.len);
    while (items.length < patch.len) items.push(null);
  }
  for (const [i, item] of patch.set ?? []) items[i] = item;
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

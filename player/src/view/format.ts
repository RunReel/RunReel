/** Short text for a trace value, as shown in cells, node labels and the variables pane. */

import type { HeapObject, Value } from "../core/trace";

const MAX_TEXT = 40;

export function formatValue(value: unknown, heap: Record<string, HeapObject>, depth = 0): string {
  const text = format(value, heap, depth);
  return text.length <= MAX_TEXT ? text : `${text.slice(0, MAX_TEXT - 1)}…`;
}

function format(value: unknown, heap: Record<string, HeapObject>, depth: number): string {
  if (value === null) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return depth === 0 ? value : JSON.stringify(value);
  if (Array.isArray(value)) return value.map((v) => format(v, heap, depth + 1)).join(": ");
  if (typeof value !== "object") return String(value);
  const tagged = value as Record<string, unknown>;
  if ("inf" in tagged) return tagged.inf === 1 ? "∞" : "-∞";
  if ("nan" in tagged) return "nan";
  if ("bigint" in tagged) return String(tagged.bigint);
  if ("ref" in tagged) return formatObject(heap[String(tagged.ref)], heap, depth);
  return "?";
}

function formatObject(obj: HeapObject | undefined, heap: Record<string, HeapObject>, depth: number): string {
  if (!obj) return "…";
  if (depth > 1) return obj.t === "repr" ? obj.cls : `${obj.cls}(…)`;
  const more = obj.more ? ", …" : "";
  const items = (obj.items ?? []).map((item) => format(item, heap, depth + 1)).join(", ");
  switch (obj.t) {
    case "seq":
      if (obj.cls === "tuple") return `(${items}${obj.items?.length === 1 ? "," : ""}${more})`;
      if (obj.cls === "set" || obj.cls === "frozenset") return `{${items}${more}}`;
      return `[${items}${more}]`;
    case "map":
      return `{${items}${more}}`;
    case "obj": {
      const fields = Object.entries(obj.fields ?? {}).map(([k, v]) => `${k}=${format(v, heap, depth + 1)}`);
      return `${obj.cls}(${fields.join(", ")})`;
    }
    default:
      return obj.v ?? obj.cls;
  }
}

/** The object a value refers to, if it is a reference. */
export function deref(value: Value | unknown, heap: Record<string, HeapObject>): [string, HeapObject] | undefined {
  if (value === null || typeof value !== "object" || Array.isArray(value) || !("ref" in value)) return undefined;
  const id = String((value as { ref: number }).ref);
  const obj = heap[id];
  return obj ? [id, obj] : undefined;
}

/** Whether a value is shown inline: a scalar or a tagged number. */
export function isScalar(value: unknown, heap: Record<string, HeapObject>): boolean {
  if (value === null || typeof value !== "object") return true;
  return !Array.isArray(value) && !deref(value, heap);
}

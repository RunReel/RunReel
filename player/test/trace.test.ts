import { describe, expect, it } from "vitest";

import { applyStep, emptyState, stateAt, type HeapObject, type State, type Step } from "../src/core/trace";
import sampleStates from "../../tests/fixtures/sample-states.json";
import sampleTrace from "../../tests/fixtures/sample-trace.json";

// The same reference files the Python tests use, so both decoders must agree exactly.
const steps = sampleTrace.steps as unknown as Step[];
const expected = sampleStates as unknown as State[];

describe("trace decoder", () => {
  it("rebuilds every state of the reference trace from its nearest keyframe", () => {
    expected.forEach((state, n) => expect(stateAt(steps, n)).toEqual(state));
  });

  it("plays forward one step at a time to the same states", () => {
    const state = emptyState();
    steps.forEach((step, n) => {
      applyStep(state, step);
      expect(state).toEqual(expected[n]);
    });
  });

  it("applies patches without changing the trace itself", () => {
    const list = (): HeapObject => ({ t: "seq", cls: "list", items: [1, 2, 3], more: 5 });
    const node = (): HeapObject => ({ t: "obj", cls: "Node", fields: { val: 1, next: null } });
    const trace: Step[] = [
      { ev: "line", line: 1, key: true, heap: { "1": list(), "2": node() } },
      {
        ev: "line",
        line: 2,
        heap: {
          // Back to front: append 7 and 8, remove the 2, then replace the 1 with 9.
          "1": { ops: [[0, 9], [1, 1, []], [3, 0, [7, 8]]], more: 0 },
          "2": { set: { next: { ref: 1 } }, del: ["val"] },
        },
      },
    ];
    expect(stateAt(trace, 1).heap).toEqual({
      "1": { t: "seq", cls: "list", items: [9, 3, 7, 8] },
      "2": { t: "obj", cls: "Node", fields: { next: { ref: 1 } } },
    });
    expect(stateAt(trace, 0).heap).toEqual({ "1": list(), "2": node() });
  });

  it("keeps a field named __proto__ as an ordinary field", () => {
    const trace = JSON.parse(
      '[{"ev":"line","line":1,"key":true,"heap":{"1":{"t":"obj","cls":"C","fields":{}}}},' +
        '{"ev":"line","line":2,"heap":{"1":{"set":{"__proto__":{"ref":1}}}}}]',
    ) as Step[];
    const fields = stateAt(trace, 1).heap["1"]?.fields;
    expect(Object.keys(fields ?? {})).toEqual(["__proto__"]);
    expect(Object.getPrototypeOf(fields)).toBe(Object.prototype);
  });

  it("rejects a trace that doesn't start with a keyframe", () => {
    expect(() => stateAt([{ ev: "line", line: 1 }], 0)).toThrow("keyframe");
  });
});

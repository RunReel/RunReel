import { describe, expect, it } from "vitest";

import { applyStep, emptyState, stateAt, type State, type Step } from "../src/core/trace";
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

  it("applies item patches without changing the trace itself", () => {
    const trace: Step[] = [
      { ev: "line", line: 1, key: true, heap: { "1": { t: "seq", cls: "list", items: [1, 2, 3], more: 5 } } },
      { ev: "line", line: 2, heap: { "1": { len: 4, set: [[0, 9], [3, 7]], more: 0 } } },
    ];
    expect(stateAt(trace, 1).heap["1"]).toEqual({ t: "seq", cls: "list", items: [9, 2, 3, 7] });
    expect(stateAt(trace, 0).heap["1"]).toEqual({ t: "seq", cls: "list", items: [1, 2, 3], more: 5 });
  });

  it("rejects a trace that doesn't start with a keyframe", () => {
    expect(() => stateAt([{ ev: "line", line: 1 }], 0)).toThrow("keyframe");
  });
});

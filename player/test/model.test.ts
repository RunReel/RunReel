import { describe, expect, it } from "vitest";

import type { Step } from "../src/core/trace";
import { actionForKey, endNote, firstSteps, moveMs, printedBy, SPEEDS, stepFromHash, stepMs, type TraceFile } from "../src/ui/model";

describe("player model", () => {
  it("finds the first step that runs each line", () => {
    const steps = [3, 4, 3, 5].map((line, i) => ({ ev: "line", line, ...(i === 0 ? { key: true } : {}) })) as Step[];
    expect([...firstSteps(steps)]).toEqual([[3, 0], [4, 1], [5, 3]]);
  });

  it("shows only what was printed up to the current step", () => {
    const out: [number, string][] = [[1, "a\n"], [4, "b\n"]];
    expect(printedBy(out, 0)).toBe("");
    expect(printedBy(out, 3)).toBe("a\n");
    expect(printedBy(out, 4)).toBe("a\nb\n");
    expect(printedBy(undefined, 9)).toBe("");
  });

  it("says how a run that ended early was stopped", () => {
    const trace = (extra: Partial<TraceFile>): TraceFile => ({
      schema: 1, language: "python", source: { file: "a.py", text: "", entry: "" }, steps: [], ...extra,
    });
    expect(endNote(trace({}))).toBe("");
    expect(endNote(trace({ truncated: true }))).toBe("The run went on past the step limit; only the first steps were recorded.");
    expect(endNote(trace({ stopped: "timeout" }))).toBe("The run was stopped here, at the time limit.");
    expect(endNote(trace({ stopped: "interrupt" }))).toBe("The run was stopped here, with Ctrl+C.");
    expect(endNote(trace({ truncated: true, stopped: "timeout" }))).toBe(
      "The run went on past the step limit, so only the first steps were recorded, and it was stopped at the time limit.",
    );
  });

  it("slows the moves down with the playback, so 0.1× is slow motion", () => {
    expect(SPEEDS).toEqual([0.1, 0.2, 0.5, 1, 2, 4, 8]);
    expect(SPEEDS.map(stepMs)).toEqual([5000, 2500, 1000, 500, 250, 125, 62.5]);
    expect(SPEEDS.map(moveMs)).toEqual([2600, 1300, 520, 260, 260, 260, 260]);
    for (const speed of SPEEDS.filter((s) => s <= 1)) expect(moveMs(speed)).toBeLessThan(stepMs(speed));
  });

  it("reads #step=n links and keeps them in range", () => {
    expect(stepFromHash("#step=12", 50)).toBe(12);
    expect(stepFromHash("#step=99", 50)).toBe(49);
    expect(stepFromHash("", 50)).toBe(0);
    expect(stepFromHash("#other", 50)).toBe(0);
  });

  it("maps the keyboard shortcuts", () => {
    expect([" ", "ArrowLeft", "j", "ArrowRight", "K", "Home", "End", "x"].map(actionForKey)).toEqual([
      "toggle", "back", "back", "forward", "forward", "first", "last", undefined,
    ]);
  });
});

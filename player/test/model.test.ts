import { describe, expect, it } from "vitest";

import type { Step } from "../src/core/trace";
import { actionForKey, firstSteps, printedBy, stepFromHash } from "../src/ui/model";

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

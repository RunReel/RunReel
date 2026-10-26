/** The player's logic that doesn't touch the page, kept apart so it can be tested without a browser. */

import type { Step, Value } from "../core/trace";

export interface TraceFile {
  schema: number;
  language: string;
  source: { file: string; text: string; entry: string };
  steps: Step[];
  result?: Value;
  error?: string;
  stdout?: [number, string][];
  truncated?: true;
  stopped?: "timeout" | "interrupt";
}

/** The badge for a run that was stopped, and how it was stopped. */
export const STOPS = {
  timeout: { badge: "timed out", how: "at the time limit" },
  interrupt: { badge: "interrupted", how: "with Ctrl+C" },
} as const;

/** What the last step says about a run that ended early, or "" if it didn't. */
export function endNote(trace: TraceFile): string {
  const how = trace.stopped ? STOPS[trace.stopped].how : "";
  if (trace.truncated) {
    return how
      ? `The run went on past the step limit, so only the first steps were recorded, and it was stopped ${how}.`
      : "The run went on past the step limit; only the first steps were recorded.";
  }
  return how ? `The run was stopped here, ${how}.` : "";
}

/** For each source line, the first step that runs it, so lines can be shaded once they've run. */
export function firstSteps(steps: readonly Step[]): Map<number, number> {
  const first = new Map<number, number>();
  steps.forEach((step, n) => {
    if (!first.has(step.line)) first.set(step.line, n);
  });
  return first;
}

/** Everything printed up to and including step n. */
export function printedBy(stdout: readonly [number, string][] | undefined, n: number): string {
  return (stdout ?? []).filter(([step]) => step <= n).map(([, text]) => text).join("");
}

/** The step a link like #step=12 points to, clamped to the trace; 0 when there is none. */
export function stepFromHash(hash: string, count: number): number {
  const match = /(?:^#|&)step=(\d+)/.exec(hash);
  const n = match ? Number(match[1]) : 0;
  return Math.min(Math.max(n, 0), Math.max(count - 1, 0));
}

export type Action = "toggle" | "back" | "forward" | "first" | "last";

/** Keyboard shortcuts: Space plays or pauses, ← and J step back, → and K step forward. */
export function actionForKey(key: string): Action | undefined {
  switch (key) {
    case " ":
      return "toggle";
    case "ArrowLeft":
    case "j":
    case "J":
      return "back";
    case "ArrowRight":
    case "k":
    case "K":
      return "forward";
    case "Home":
      return "first";
    case "End":
      return "last";
    default:
      return undefined;
  }
}

import { describe, expect, it } from "vitest";

import { stateAt, type State, type Step } from "../src/core/trace";
import { inferViews, type ArrayView, type GraphView, type GridView, type TreeView } from "../src/view/infer";
import binarySearch from "../../tests/fixtures/golden/py312/binary_search.json";
import bstInsert from "../../tests/fixtures/golden/py312/bst_insert.json";
import dijkstra from "../../tests/fixtures/golden/py312/dijkstra.json";
import lcs from "../../tests/fixtures/golden/py312/lcs.json";

const steps = (trace: { steps: unknown }) => trace.steps as Step[];
const viewsAt = (trace: { steps: unknown; source?: { text: string } }, n: number) =>
  inferViews(stateAt(steps(trace), n), n > 0 ? stateAt(steps(trace), n - 1) : undefined, trace.source?.text.split("\n"));

/** One frame whose locals are given, with the heap objects they refer to. */
const stateWith = (locals: Record<string, unknown>, heap: Record<string, unknown>): State =>
  ({ ev: "line", line: 1, stack: [{ fid: 1, fn: "f", line: 1, locals }], heap }) as State;

describe("shape inference", () => {
  it("shows a list of numbers as an array with index pointers", () => {
    // Step 9: lo=4, hi=6, mid=5, just before `if a[mid] == target`.
    const [view] = viewsAt(binarySearch, 9) as [ArrayView];
    expect(view.kind).toBe("array");
    expect(view.label).toBe("a");
    expect(view.cells.map((c) => c.text)).toEqual(["1", "3", "4", "7", "9", "11", "15"]);
    expect(view.pointers).toEqual([
      { name: "lo", index: 4 },
      { name: "hi", index: 6 },
      { name: "mid", index: 5 },
    ]);
  });

  it("marks the cells that changed since the step before", () => {
    const trace = {
      steps: [
        { ev: "line", line: 1, key: true, stack: [1], frames: { "1": { fn: "f", set: { a: { ref: 1 } } } }, heap: { "1": { t: "seq", cls: "list", items: [1, 2, 3] } } },
        { ev: "line", line: 2, heap: { "1": { ops: [[1, 9]] } } },
      ],
    };
    const [view] = viewsAt(trace, 1) as [ArrayView];
    expect(view.cells.map((c) => c.changed)).toEqual([false, true, false]);
  });

  it("shows objects with left and right as one tree from its root, with locals as marks", () => {
    // `return root` after the last insert: `node` points at 3 while `root` points at 5.
    const n = steps(bstInsert).length - 5;
    const trees = viewsAt(bstInsert, n).filter((v) => v.kind === "tree") as TreeView[];
    expect(trees).toHaveLength(1);
    const tree = trees[0]!;
    const byText = Object.fromEntries(Object.values(tree.nodes).map((node) => [node.text, node]));
    expect(byText["5"]!.key).toBe(tree.root);
    expect(tree.nodes[byText["5"]!.left!]!.text).toBe("3");
    expect(tree.nodes[byText["5"]!.right!]!.text).toBe("8");
    expect(tree.nodes[byText["3"]!.right!]!.text).toBe("4");
    expect(byText["5"]!.marks).toContain("root");
    expect(byText["3"]!.marks).toContain("node");
  });

  it("shows an adjacency dict as a graph, with dist, the current node and the edge being relaxed", () => {
    // Step 28: relaxing 2 -> 1, about to set dist[1] = 3.
    const state: State = stateAt(steps(dijkstra), 28);
    const graph = inferViews(state).find((v) => v.kind === "graph") as GraphView;
    expect(graph.label).toBe("graph");
    expect(graph.nodes.map((n) => [n.text, n.sub, n.state])).toEqual([
      ["0", "dist=0", "none"],
      ["1", "dist=4", "next"],
      ["2", "dist=1", "current"],
      ["3", "dist=∞", "none"],
    ]);
    const active = graph.edges.filter((e) => e.active);
    expect(active.map((e) => [e.from, e.to, e.weight])).toEqual([[`${graph.key}:2`, `${graph.key}:1`, "2"]]);
  });

  it("shows a list of equal lists as a grid, on the cell the line fills and the cells it reads", () => {
    // Step 39, line 9: dp[i][j] = max(dp[i - 1][j], dp[i][j - 1]) with i = 2 and j = 3.
    const [view] = viewsAt(lcs, 39) as [GridView];
    expect([view.kind, view.label, view.height, view.width]).toEqual(["grid", "dp", 8, 7]);
    expect(view.focus).toEqual({ row: 2, col: 3 });
    expect(view.deps).toEqual([{ row: 1, col: 3 }, { row: 2, col: 2 }]);
  });

  it("marks the grid cell a step filled, and keeps the focus on lines that don't index it", () => {
    // Step 34 is back on the loop line, just after line 7 set dp[2][1] to 1.
    const [view] = viewsAt(lcs, 34) as [GridView];
    const changed = view.rows.flatMap((row, r) => row.flatMap((cell, c) => (cell.changed ? [[r, c, cell.text]] : [])));
    expect(changed).toEqual([[2, 1, "1"]]);
    expect(view.focus).toEqual({ row: 2, col: 1 }); // dp[i][j] is how the code indexes it most
  });

  it("takes a list of strings for a grid only if the code indexes it as name[r][c]", () => {
    const state = stateWith({ maze: { ref: 1 }, r: 1, c: 2 }, { "1": { t: "seq", cls: "list", items: ["#..", "..#", "#.."] } });
    const [grid] = inferViews(state, undefined, ["if maze[r][c] == '#':"]) as [GridView];
    expect([grid.kind, grid.rows[1]!.map((cell) => cell.text), grid.focus]).toEqual(["grid", [".", ".", "#"], { row: 1, col: 2 }]);
    expect(inferViews(state, undefined, ["for row in maze:"])[0]!.kind).toBe("array"); // a list of words
  });

  it("keeps a list of tuples an array and a ragged list off the grid", () => {
    const pairs = stateWith({ pq: { ref: 1 } }, { "1": { t: "seq", cls: "list", items: [{ ref: 2 }] }, "2": { t: "seq", cls: "tuple", items: [0, 5] } });
    expect(inferViews(pairs)[0]!.kind).toBe("array");
    const ragged = stateWith({ m: { ref: 1 } }, {
      "1": { t: "seq", cls: "list", items: [{ ref: 2 }, { ref: 3 }] },
      "2": { t: "seq", cls: "list", items: [1, 2] },
      "3": { t: "seq", cls: "list", items: [1] },
    });
    expect(inferViews(ragged)).toEqual([]);
  });

  it("shows a window of a big grid around its focus, with the grid's own numbers", () => {
    const heap: Record<string, unknown> = { "1": { t: "seq", cls: "list", items: Array.from({ length: 100 }, (_, r) => ({ ref: r + 2 })) } };
    for (let r = 0; r < 100; r++) heap[String(r + 2)] = { t: "seq", cls: "list", items: Array.from({ length: 100 }, () => 0) };
    const [view] = inferViews(stateWith({ g: { ref: 1 }, r: 70, c: 5 }, heap), undefined, ["g[r][c] += 1"]) as [GridView];
    expect([view.top, view.left, view.rows.length, view.rows[0]!.length]).toEqual([50, 0, 40, 60]);
    expect([view.height, view.width, view.focus]).toEqual([100, 100, { row: 70, col: 5 }]);
    expect(view.rows[20]![5]!.key).toBe("1:70:5");
  });

  it("draws nothing for values it doesn't recognise", () => {
    const state: State = { ev: "line", line: 1, stack: [{ fid: 1, fn: "f", line: 1, locals: { s: { ref: 1 } } }], heap: { "1": { t: "repr", cls: "function", v: "<function g>" } } };
    expect(inferViews(state)).toEqual([]);
  });
});

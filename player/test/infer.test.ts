import { describe, expect, it } from "vitest";

import { stateAt, type State, type Step } from "../src/core/trace";
import { inferViews, type ArrayView, type GraphView, type TreeView } from "../src/view/infer";
import binarySearch from "../../tests/fixtures/golden/binary_search.json";
import bstInsert from "../../tests/fixtures/golden/bst_insert.json";
import dijkstra from "../../tests/fixtures/golden/dijkstra.json";

const steps = (trace: { steps: unknown }) => trace.steps as Step[];
const viewsAt = (trace: { steps: unknown }, n: number) =>
  inferViews(stateAt(steps(trace), n), n > 0 ? stateAt(steps(trace), n - 1) : undefined);

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
    // Step 31: relaxing 2 -> 1, about to set dist[1] = 3.
    const state: State = stateAt(steps(dijkstra), 31);
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

  it("draws nothing for values it doesn't recognise", () => {
    const state: State = { ev: "line", line: 1, stack: [{ fid: 1, fn: "f", line: 1, locals: { s: { ref: 1 } } }], heap: { "1": { t: "repr", cls: "function", v: "<function g>" } } };
    expect(inferViews(state)).toEqual([]);
  });
});

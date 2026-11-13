import { describe, expect, it } from "vitest";

import { stateAt, type State, type Step } from "../src/core/trace";
import { inferViews, type ArrayView, type GraphView, type GridView, type ListView, type TreeView } from "../src/view/infer";
import binarySearch from "../../tests/fixtures/golden/py312/binary_search.json";
import bstInsert from "../../tests/fixtures/golden/py312/bst_insert.json";
import dijkstra from "../../tests/fixtures/golden/py312/dijkstra.json";
import lcs from "../../tests/fixtures/golden/py312/lcs.json";
import reverseList from "../../tests/fixtures/golden/py312/reverse_list.json";

const steps = (trace: { steps: unknown }) => trace.steps as Step[];
const viewsAt = (trace: { steps: unknown; source?: { text: string } }, n: number) =>
  inferViews(stateAt(steps(trace), n), n > 0 ? stateAt(steps(trace), n - 1) : undefined, trace.source?.text.split("\n"));

/** One frame whose locals are given, with the heap objects they refer to. */
const stateWith = (locals: Record<string, unknown>, heap: Record<string, unknown>): State =>
  ({ ev: "line", line: 1, stack: [{ fid: 1, fn: "f", line: 1, locals }], heap }) as State;

/** Linked list nodes with ids "1", "2", …: [value, id next points at (null for None), fields to add]. */
const nodes = (...list: [number | string, number | null, Record<string, unknown>?][]) =>
  Object.fromEntries(list.map(([value, next, more], i) => [String(i + 1), { t: "obj", cls: "Node", fields: { value, next: next === null ? null : { ref: next }, ...more } }]));
const texts = (view: ListView) => view.rows.map((row) => row.nodes.map((id) => view.nodes[id]!.text));

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

  it("puts a pointer under the arrays the code indexes with it, whatever it's called", () => {
    const list = (...items: number[]) => ({ t: "seq", cls: "list", items });
    const heap = { "1": list(3, 1, 2), "2": list(6), "3": list(4, 5, 6) };
    const state = stateWith({ a: { ref: 1 }, result: { ref: 2 }, b: { ref: 3 }, i: 1, j: 2, p: 0, lo: 0 }, heap);
    const lines = ["for i in range(len(a)):", "    result.append(a[i] * 2)", "    if b[j] > a[p]:", "        y = a[b[j]]  # j indexes b here, not a"];
    const views = inferViews(state, undefined, lines) as ArrayView[];
    // lo indexes nothing, so it goes under every array the code indexes; result is only appended to.
    expect(Object.fromEntries(views.map((v) => [v.label, v.pointers.map((p) => p.name)]))).toEqual({ a: ["i", "p", "lo"], result: [], b: ["j", "lo"] });
  });

  it("shows floats as Python prints them", () => {
    const state = stateWith({ xs: { ref: 1 } }, { "1": { t: "seq", cls: "list", items: [{ float: "1.0" }, 0.5, { float: "-0.0" }, { float: "1e-05" }] } });
    expect((inferViews(state)[0] as ArrayView).cells.map((c) => c.text)).toEqual(["1.0", "0.5", "-0.0", "1e-05"]);
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

  it("takes a dict of lists for a graph only if the lists name its keys, and a dict of dicts too", () => {
    const map = (...items: unknown[]) => ({ t: "map", cls: "dict", items });
    const list = (...items: unknown[]) => ({ t: "seq", cls: "list", items });
    const food = { "1": map(["fruit", { ref: 2 }]), "2": list("apple", "pear") };
    expect(inferViews(stateWith({ menu: { ref: 1 } }, food))).toEqual([]);
    const roads = { "1": map(["a", { ref: 2 }], ["b", { ref: 3 }]), "2": map(["b", 7]), "3": map(["a", 7]) };
    const [graph] = inferViews(stateWith({ roads: { ref: 1 } }, roads)) as [GraphView];
    // Every road has a twin back with the same weight, so it's undirected: one edge each.
    expect([graph.directed, graph.edges.map((e) => [e.from, e.to, e.weight])]).toEqual([false, [['1:"a"', '1:"b"', "7"]]]);
    // Walked from b to a, the one edge kept (a to b) still lights up.
    const walked = inferViews(stateWith({ roads: { ref: 1 }, u: "b", v: "a" }, roads), undefined, ["for v in roads[u]:"])[0] as GraphView;
    expect(walked.edges.map((e) => e.active)).toEqual([true]);
    const oneWay = { ...roads, "3": map(["a", 7], ["a", 2]) }; // b goes back to a twice, once at 2
    expect((inferViews(stateWith({ roads: { ref: 1 } }, oneWay))[0] as GraphView).directed).toBe(true);
  });

  it("keeps an edge listed twice as two edges", () => {
    const heap = { "1": { t: "map", cls: "dict", items: [[0, { ref: 2 }], [1, { ref: 3 }]] }, "2": { t: "seq", cls: "list", items: [1, 1] }, "3": { t: "seq", cls: "list", items: [] } };
    const [graph] = inferViews(stateWith({ g: { ref: 1 } }, heap)) as [GraphView];
    expect(graph.edges.map((e) => [e.key, e.nth])).toEqual([["1:0->1:1", 0], ["1:0->1:1#1", 1]]);
  });

  it("finds the node being processed and its neighbour from how the code walks the graph", () => {
    // Unusual names: at is what the code indexes g with, nb is what it loops over. A caller's at
    // (the outer frame) mustn't win over the running function's own. indegree is indexed by
    // node, so it labels the nodes; reached is a set of nodes, so they count as visited.
    const map = (...items: unknown[]) => ({ t: "map", cls: "dict", items });
    const heap = {
      "1": map([0, { ref: 2 }], [1, { ref: 3 }], [2, { ref: 4 }]),
      "2": { t: "seq", cls: "list", items: [1, 2] },
      "3": { t: "seq", cls: "list", items: [2] },
      "4": { t: "seq", cls: "list", items: [] },
      "5": map([0, 0], [1, 0], [2, 1]),
      "6": { t: "seq", cls: "set", items: [0] },
    };
    const frame = (fid: number, locals: Record<string, unknown>) => ({ fid, fn: "f", line: 1, locals });
    const state = { ev: "line", line: 2, heap, stack: [frame(1, { g: { ref: 1 }, at: 0 }), frame(2, { g: { ref: 1 }, at: 1, nb: 2, indegree: { ref: 5 }, reached: { ref: 6 } })] } as State;
    const lines = ["for nb in g[at]:", "    indegree[nb] -= 1"];
    const [graph] = inferViews(state, undefined, lines) as [GraphView];
    expect(graph.nodes.map((n) => [n.text, n.state, n.sub])).toEqual([["0", "visited", "indegree=0"], ["1", "current", "indegree=0"], ["2", "next", "indegree=1"]]);
    expect(graph.edges.filter((e) => e.active).map((e) => [e.from, e.to])).toEqual([["1:1", "1:2"]]);
    // A list of True and False indexed by node marks the visited ones too.
    const flags = { ...heap, "7": { t: "seq", cls: "list", items: [false, false, true] } };
    const flagged = { ...state, heap: flags, stack: [frame(2, { g: { ref: 1 }, at: 1, done_yet: { ref: 7 } })] } as State;
    const [g2] = inferViews(flagged, undefined, ["for nb in g[at]:", "    done_yet[at] = True"]) as [GraphView];
    expect(g2.nodes.map((n) => n.state)).toEqual(["none", "current", "visited"]);
    // Two names index g; the one used nearer the running line (line 4) is the node being processed.
    const loops = ["for n in g:", "    for m in g[n]:", "        pass", "for nb in g[at]:"];
    const leftover = { ...state, line: 4, stack: [frame(2, { g: { ref: 1 }, n: 2, at: 0 })] } as State;
    expect((inferViews(leftover, undefined, loops)[0] as GraphView).nodes.find((x) => x.state === "current")!.text).toBe("0");
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

  it("shows objects with next as a linked list, a row per chain, with the pointers on it", () => {
    // Step 61, line 27: reverse has just set cur.next = prev, so 2 now points back at 1.
    const [view] = viewsAt(reverseList, 61) as [ListView];
    expect([view.kind, view.label]).toEqual(["list", "head"]);
    expect(texts(view)).toEqual([["2", "1"], ["3", "4", "5"]]);
    expect(view.rows.map((row) => row.end)).toEqual([{ kind: "none" }, { kind: "none" }]);
    const relinked = Object.values(view.nodes).filter((node) => node.relinked).map((node) => node.text);
    expect(relinked).toEqual(["2"]);
    expect(view.pointers.map((p) => [p.name, view.nodes[p.node]!.text])).toEqual([["head", "1"], ["prev", "1"], ["cur", "2"], ["nxt", "3"]]);
    // Step 34, the end of Node.__init__ for 4: the title stays build's head, not the new node's self.
    expect(viewsAt(reverseList, 34).find((v) => v.kind === "list")!.label).toBe("head");
  });

  it("ends a row with an arrow back into a loop, or across to the list it joins", () => {
    const loop = nodes([3, 2], [2, 3], [0, 4], [-4, 2], [5, 3]);
    const [view] = inferViews(stateWith({ head: { ref: 1 }, b: { ref: 5 } }, loop)) as [ListView];
    expect(view.rows).toEqual([
      { nodes: ["1", "2", "3", "4"], skipped: 0, end: { kind: "node", to: "2" } },
      { nodes: ["5"], skipped: 0, end: { kind: "node", to: "3" } },
    ]);
  });

  it("puts the row with the oldest node first, so rows hold still as nodes move between them", () => {
    // 3 -> 1 starts at a newer node than 2 does, but holds the oldest node.
    const [view] = inferViews(stateWith({ prev: { ref: 3 }, cur: { ref: 2 } }, nodes([1, null], [2, null], [3, 1]))) as [ListView];
    expect(texts(view)).toEqual([["3", "1"], ["2"]]);
  });

  it("keeps a doubly linked node's prev, and finds a list through the object holding its head", () => {
    const heap = { "9": { t: "obj", cls: "LinkedList", fields: { head: { ref: 1 }, size: 2 } }, ...nodes(["a", 2, { prev: null }], ["b", null, { prev: { ref: 1 } }]) };
    const [view] = inferViews(stateWith({ ll: { ref: 9 } }, heap)) as [ListView];
    expect([view.label, texts(view), view.pointers]).toEqual(["ll.head", [['"a"', '"b"']], [{ name: "ll.head", node: "1" }]]);
    expect([view.nodes["1"]!.prev, view.nodes["2"]!.prev]).toEqual([{ to: null, relinked: false }, { to: "1", relinked: false }]);
  });

  it("shows a stretch of a long list, where the most pointers are", () => {
    const long = nodes(...Array.from({ length: 100 }, (_, i): [number, number | null] => [i, i < 99 ? i + 2 : null]));
    const [view] = inferViews(stateWith({ head: { ref: 1 }, cur: { ref: 61 } }, long)) as [ListView];
    const [row] = view.rows;
    expect([row!.skipped, row!.nodes.length, view.nodes[row!.nodes[0]!]!.text, row!.end]).toEqual([55, 30, "55", { kind: "more", count: 15 }]);
    expect(view.pointers).toEqual([{ name: "cur", node: "61" }]); // head is off the left
  });

  it("finds lists and trees by how their objects link, whatever the fields are called", () => {
    const obj = (cls: string, fields: Record<string, unknown>) => ({ t: "obj", cls, fields });
    const ref = (n: number) => ({ ref: n });
    const list = { "1": obj("Cell", { val: 1, link: ref(2) }), "2": obj("Cell", { val: 2, link: null }) };
    expect(texts(inferViews(stateWith({ p: ref(1) }, list))[0] as ListView)).toEqual([["1", "2"]]);
    // r is set before l, and up points back at the parent: l is still the left, and up isn't a child.
    const tree = {
      "1": obj("T", { v: 5, r: ref(3), l: ref(2), up: null }),
      "2": obj("T", { v: 3, r: null, l: null, up: ref(1) }),
      "3": obj("T", { v: 8, r: null, l: null, up: ref(1) }),
    };
    const [t] = inferViews(stateWith({ root: ref(1) }, tree)) as [TreeView];
    expect([t.kind, t.nodes[t.nodes["1"]!.left!]!.text, t.nodes[t.nodes["1"]!.right!]!.text]).toEqual(["tree", "3", "8"]);
    // With one child so far, l and up point back at each other, but up says it's a parent.
    const young = { "1": obj("T", { v: 5, r: null, l: ref(2), up: null }), "2": obj("T", { v: 3, r: null, l: null, up: ref(1) }) };
    const [y] = inferViews(stateWith({ root: ref(1) }, young)) as [TreeView];
    expect([y.kind, y.nodes[y.nodes["1"]!.left!]!.text]).toEqual(["tree", "3"]);
    // back and fwd point back at each other: a doubly linked list, with back as prev though it was set first.
    const dll = { "1": obj("D", { item: "a", back: null, fwd: ref(2) }), "2": obj("D", { item: "b", back: ref(1), fwd: null }) };
    const [d] = inferViews(stateWith({ a: ref(1) }, dll)) as [ListView];
    expect([texts(d), d.nodes["2"]!.prev, d.nodes["1"]!.prev]).toEqual([[['"a"', '"b"']], { to: "1", relinked: false }, { to: null, relinked: false }]);
  });

  it("doesn't guess a shape from links it hasn't seen, or from parents alone", () => {
    const obj = (cls: string, fields: Record<string, unknown>) => ({ t: "obj", cls, fields });
    const lone = { "1": obj("Cell", { val: 1, link: null }) };
    expect(inferViews(stateWith({ c: { ref: 1 } }, lone))).toEqual([]); // nothing links yet
    expect(inferViews(stateWith({ c: { ref: 1 } }, { "1": obj("Cell", { val: 1, next: null }) }))[0]!.kind).toBe("list"); // but next says so
    const other = { "1": obj("Cell", { val: 1, link: { ref: 2 } }), "2": obj("Tag", { name: "x" }) };
    expect(inferViews(stateWith({ c: { ref: 1 } }, other))).toEqual([]); // a link to another class
    const forest = { "1": obj("Set", { size: 2, parent: null }), "2": obj("Set", { size: 1, parent: { ref: 1 } }) };
    expect(inferViews(stateWith({ s: { ref: 2 } }, forest))).toEqual([]);
  });

  it("leaves objects with left or right to the tree view, even with a next", () => {
    const heap = { ...nodes([1, null]), "9": { t: "obj", cls: "Tree", fields: { val: 2, left: null, right: null, next: null } } };
    const views = inferViews(stateWith({ root: { ref: 9 }, head: { ref: 1 } }, heap));
    expect(views.map((v) => v.kind)).toEqual(["tree", "list"]);
    expect(Object.keys((views[1] as ListView).nodes)).toEqual(["1"]);
  });

  it("keeps each view in its place as the code calls into a function and returns", () => {
    // Inside insert or Node.__init__ the running function's names come first, but the views
    // stay in the order the outer frame has them, so nothing jumps up or down the page.
    for (const trace of [bstInsert, reverseList]) {
      let last: string[] = [];
      steps(trace).forEach((_, n) => {
        const keys = viewsAt(trace, n).map((v) => v.key);
        expect(keys.filter((k) => last.includes(k))).toEqual(last.filter((k) => keys.includes(k)));
        last = keys;
      });
    }
  });

  it("draws nothing for values it doesn't recognise", () => {
    const state: State = { ev: "line", line: 1, stack: [{ fid: 1, fn: "f", line: 1, locals: { s: { ref: 1 } } }], heap: { "1": { t: "repr", cls: "function", v: "<function g>" } } };
    expect(inferViews(state)).toEqual([]);
  });
});

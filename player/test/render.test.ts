import { describe, expect, it } from "vitest";

import { stateAt, type Step } from "../src/core/trace";
import { composeScene } from "../src/render/compose";
import { sceneToSvg, type Item } from "../src/render/scene";
import { inferViews, type GridView } from "../src/view/infer";
import binarySearch from "../../tests/fixtures/golden/py312/binary_search.json";
import bstInsert from "../../tests/fixtures/golden/py312/bst_insert.json";
import dijkstra from "../../tests/fixtures/golden/py312/dijkstra.json";
import lcs from "../../tests/fixtures/golden/py312/lcs.json";

const TRACES = { binary_search: binarySearch, bst_insert: bstInsert, dijkstra, lcs } as const;
const sceneAt = (trace: { steps: unknown; source: { text: string } }, n: number) => {
  const steps = trace.steps as Step[];
  const lines = trace.source.text.split("\n");
  return composeScene(inferViews(stateAt(steps, n), n > 0 ? stateAt(steps, n - 1) : undefined, lines));
};

describe("renderers", () => {
  // Golden SVGs at a few steps of each example; update with `npx vitest run -u`.
  for (const [name, n] of [["binary_search", 9], ["binary_search", 16], ["bst_insert", 83], ["dijkstra", 28], ["dijkstra", 59], ["lcs", 34], ["lcs", 39]] as const) {
    it(`draws ${name} at step ${n}`, async () => {
      await expect(sceneToSvg(sceneAt(TRACES[name], n))).toMatchFileSnapshot(`golden/${name}-${n}.svg`);
    });
  }

  it("keeps an object's element key and place as the tree grows", () => {
    const keyed = (n: number) => new Map(sceneAt(bstInsert, n).items.filter((i) => i.type === "circle").map((i) => [i.key, i] as const));
    const early = keyed(29); // 5 with 3 on its left
    const late = keyed(87); // the full tree
    for (const [key, item] of early) {
      expect(late.has(key)).toBe(true);
      expect((late.get(key) as Item & { y: number }).y).toBe((item as Item & { y: number }).y);
    }
    expect(late.size).toBe(5);
  });

  it("outlines the grid cell being filled and shades the cells it reads", () => {
    const steps = lcs.steps as Step[];
    const [grid] = inferViews(stateAt(steps, 39), stateAt(steps, 38), lcs.source.text.split("\n")) as [GridView];
    const boxes = sceneAt(lcs, 39).items.filter((i) => i.type === "box");
    expect(boxes.filter((i) => i.cls === "rr-focus").map((i) => i.key)).toEqual([`${grid.key}:focus`]);
    expect(boxes.filter((i) => i.cls === "rr-read").map((i) => i.key).sort()).toEqual([`${grid.key}:1:3`, `${grid.key}:2:2`]);
  });

  it("highlights the edge being relaxed", () => {
    const active = sceneAt(dijkstra, 28).items.filter((i) => i.type === "line" && i.cls.includes("rr-active"));
    expect(active).toHaveLength(1);
    expect(active[0]!.type === "line" && active[0]!.text).toBe("2");
  });

  it("escapes text so values can't inject markup", () => {
    const svg = sceneToSvg({ width: 10, height: 10, items: [{ key: "k", type: "label", x: 0, y: 0, text: "<script>&", cls: "" }] });
    expect(svg).toContain("&lt;script&gt;&amp;");
    expect(svg).not.toContain("<script>");
  });
});

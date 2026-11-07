import type { View } from "../view/infer";
import { renderArray } from "./array";
import { renderGraph } from "./graph";
import { renderGrid } from "./grid";
import { renderList } from "./list";
import type { Item, Scene } from "./scene";
import { renderTree } from "./tree";

const PAD = 16;
const TITLE = 22;

/** All of a step's views stacked top to bottom, each under its variable name. */
export function composeScene(views: View[]): Scene {
  const items: Item[] = [];
  let y = PAD;
  let width = 0;
  for (const view of views) {
    items.push({ key: `title:${view.key}`, type: "label", x: PAD, y: y + 12, text: view.label, cls: "rr-title" });
    y += TITLE + (view.kind === "array" ? 14 : 4);
    const drawn = render(view, PAD, y);
    items.push(...drawn.items);
    width = Math.max(width, drawn.width + 2 * PAD);
    y += drawn.height + PAD;
  }
  return { width: Math.max(width, 200), height: Math.max(y, 60), items };
}

function render(view: View, x: number, y: number): { items: Item[]; width: number; height: number } {
  switch (view.kind) {
    case "array":
      return renderArray(view, x, y);
    case "grid":
      return renderGrid(view, x, y);
    case "tree":
      return renderTree(view, x, y);
    case "list":
      return renderList(view, x, y);
    case "graph":
      return renderGraph(view, x, y);
  }
}

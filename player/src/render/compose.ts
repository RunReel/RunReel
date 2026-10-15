import type { View } from "../view/infer";
import { renderArray } from "./array";
import { renderGraph } from "./graph";
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
    const drawn = view.kind === "array" ? renderArray(view, PAD, y) : view.kind === "tree" ? renderTree(view, PAD, y) : renderGraph(view, PAD, y);
    items.push(...drawn.items);
    width = Math.max(width, drawn.width + 2 * PAD);
    y += drawn.height + PAD;
  }
  return { width: Math.max(width, 200), height: Math.max(y, 60), items };
}

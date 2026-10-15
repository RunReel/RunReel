/**
 * A scene is what the renderers produce: keyed shapes with positions. The same key in two
 * scenes is the same element, so the player moves it instead of redrawing it, and the
 * movement is animated by CSS.
 */

export type Item =
  | { key: string; type: "box"; x: number; y: number; w: number; h: number; text: string; cls: string }
  | { key: string; type: "circle"; x: number; y: number; r: number; text: string; sub?: string; cls: string }
  | { key: string; type: "label"; x: number; y: number; text: string; cls: string; anchor?: "start" | "middle" | "end" }
  | { key: string; type: "line"; x1: number; y1: number; x2: number; y2: number; cls: string; arrow?: boolean; text?: string };

export interface Scene {
  width: number;
  height: number;
  items: Item[];
}

export const ARROW_DEFS =
  '<defs><marker id="rr-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">' +
  '<path d="M0,0L10,5L0,10z" class="rr-arrowhead"/></marker></defs>';

/** The scene as SVG markup: what the player draws and what snapshot tests compare. */
export function sceneToSvg(scene: Scene): string {
  const body = scene.items.map(itemToSvg).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${scene.width} ${scene.height}" width="${scene.width}" height="${scene.height}">${ARROW_DEFS}${body}</svg>`;
}

export function itemToSvg(item: Item): string {
  return `<g data-key="${esc(item.key)}" class="rr-${item.type} ${item.cls}"${transform(item)}>${itemInner(item)}</g>`;
}

export function transform(item: Item): string {
  return item.type === "line" ? "" : ` style="transform: translate(${round(item.x)}px, ${round(item.y)}px)"`;
}

/** The markup inside an item's group, drawn relative to its position. */
export function itemInner(item: Item): string {
  switch (item.type) {
    case "box":
      return `<rect width="${item.w}" height="${item.h}" rx="4"/><text x="${item.w / 2}" y="${item.h / 2}" dy="0.35em" text-anchor="middle">${esc(item.text)}</text>`;
    case "circle":
      return (
        `<circle r="${item.r}"/><text dy="0.35em" text-anchor="middle">${esc(item.text)}</text>` +
        (item.sub !== undefined ? `<text class="rr-sub" y="${item.r + 14}" text-anchor="middle">${esc(item.sub)}</text>` : "")
      );
    case "label":
      return `<text text-anchor="${item.anchor ?? "start"}">${esc(item.text)}</text>`;
    case "line": {
      // The weight sits 40% of the way along, nudged to one side, so crossing edges' weights don't collide.
      const len = Math.hypot(item.x2 - item.x1, item.y2 - item.y1) || 1;
      const wx = item.x1 + (item.x2 - item.x1) * 0.4 + ((item.y2 - item.y1) / len) * 9;
      const wy = item.y1 + (item.y2 - item.y1) * 0.4 - ((item.x2 - item.x1) / len) * 9;
      const mid = item.text !== undefined ? `<text class="rr-weight" x="${round(wx)}" y="${round(wy)}" dy="0.35em" text-anchor="middle">${esc(item.text)}</text>` : "";
      const marker = item.arrow ? ' marker-end="url(#rr-arrow)"' : "";
      return `<line x1="${round(item.x1)}" y1="${round(item.y1)}" x2="${round(item.x2)}" y2="${round(item.y2)}"${marker}/>${mid}`;
    }
  }
}

export function esc(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

export function round(n: number): number {
  return Math.round(n * 10) / 10;
}

/** RunReel player: decodes a trace and draws it as an interactive reel. */
export const PLAYER_VERSION = "0.0.0";

export * from "./core/trace";
export { mount, type MountOptions, type Player } from "./ui/player";
export type { TraceFile } from "./ui/model";

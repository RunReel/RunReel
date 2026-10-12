import { describe, expect, it } from "vitest";

import { PLAYER_VERSION } from "../src/index";

describe("player", () => {
  it("exposes a semantic version string", () => {
    expect(PLAYER_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });
});

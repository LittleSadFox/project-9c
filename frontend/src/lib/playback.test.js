import { describe, expect, it } from "vitest";

import { cycleRate, nextSignedRate } from "./playback.js";

describe("playback rates", () => {
  it("starts reverse at -1x and then speeds up", () => {
    expect(nextSignedRate(-1, 1)).toBe(-1);
    expect(nextSignedRate(-1, -1)).toBe(-2);
    expect(nextSignedRate(-1, 0)).toBe(-1);
  });

  it("starts forward at 1x and then speeds up", () => {
    expect(nextSignedRate(1, -2)).toBe(1);
    expect(nextSignedRate(1, 1)).toBe(2);
    expect(nextSignedRate(1, 4)).toBe(4);
  });

  it("cycles unsigned rates", () => {
    expect(cycleRate(1)).toBe(2);
    expect(cycleRate(4)).toBe(0.25);
  });
});

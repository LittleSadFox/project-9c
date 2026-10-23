import { describe, expect, it } from "vitest";

import { clampFrame, frameFromTime, inOutValid, stepFrame, timeFromFrame } from "./frameTime.js";

describe("frameTime", () => {
  it("clamps to the last proxy frame", () => {
    expect(clampFrame(-2, 120)).toBe(0);
    expect(clampFrame(200, 120)).toBe(119);
    expect(clampFrame(15.6, 120)).toBe(16);
  });

  it("converts time and frame with fps", () => {
    expect(timeFromFrame(30, 30)).toBe(1);
    expect(frameFromTime(1, 30, 120)).toBe(30);
  });

  it("steps by a delta", () => {
    expect(stepFrame(10, -1, 120)).toBe(9);
    expect(stepFrame(0, -10, 120)).toBe(0);
    expect(stepFrame(118, 10, 120)).toBe(119);
  });

  it("requires out to be after in", () => {
    expect(inOutValid(10, 40, 120)).toBe(true);
    expect(inOutValid(40, 10, 120)).toBe(false);
    expect(inOutValid(0, 0, 120)).toBe(false);
  });
});

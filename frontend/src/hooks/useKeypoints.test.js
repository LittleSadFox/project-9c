import { describe, expect, it } from "vitest";

import { keypointsFixture } from "../test/fixtures.js";
import { frameKeypoints, windowForFrame } from "./useKeypoints.js";

describe("useKeypoints helpers", () => {
  it("snaps frames to 120-frame windows", () => {
    expect(windowForFrame(0)).toEqual({ start: 0, end: 120 });
    expect(windowForFrame(119)).toEqual({ start: 0, end: 120 });
    expect(windowForFrame(120)).toEqual({ start: 120, end: 240 });
  });

  it("reads the keypoints for one frame", () => {
    expect(frameKeypoints(keypointsFixture, 0)).toEqual(keypointsFixture.frames[0]);
    expect(frameKeypoints(keypointsFixture, 500)).toBeNull();
    expect(frameKeypoints(null, 0)).toBeNull();
  });
});

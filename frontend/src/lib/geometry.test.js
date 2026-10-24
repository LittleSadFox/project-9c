import { describe, expect, it } from "vitest";

import {
  clampPoint,
  clientToSource,
  frameFromClientX,
  pointInBBox,
  scalePoint,
  unscalePoint,
  videoContentRect,
} from "./geometry.js";

describe("geometry", () => {
  it("scales proxy pixels into the canvas", () => {
    expect(scalePoint(100, 50, 200, 100, 400, 200)).toEqual([200, 100]);
  });

  it("letterboxes object-fit contain", () => {
    const rect = videoContentRect({
      clientWidth: 200,
      clientHeight: 200,
      videoWidth: 200,
      videoHeight: 100,
    });
    expect(rect.width).toBe(200);
    expect(rect.height).toBe(100);
    expect(rect.y).toBe(50);
  });

  it("maps a click to a frame", () => {
    expect(frameFromClientX(50, { left: 0, width: 100 }, 11)).toBe(5);
  });

  it("maps a click back to source pixels", () => {
    expect(unscalePoint(200, 100, 200, 100, 400, 200)).toEqual([100, 50]);
    expect(clientToSource(50, 25, { left: 0, top: 0, width: 100, height: 50 }, 200, 100)).toEqual([
      100, 50,
    ]);
    expect(clampPoint(-4, 2000, 1920, 1080)).toEqual([0, 1079]);
    expect(pointInBBox(120, 140, [100, 100, 50, 80])).toBe(true);
    expect(pointInBBox(10, 10, [100, 100, 50, 80])).toBe(false);
  });
});

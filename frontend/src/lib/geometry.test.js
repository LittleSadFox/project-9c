import { describe, expect, it } from "vitest";

import { frameFromClientX, scalePoint, videoContentRect } from "./geometry.js";

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
});

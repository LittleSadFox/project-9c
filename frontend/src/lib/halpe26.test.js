import { describe, expect, it } from "vitest";

import { swapLeftRight } from "./halpe26.js";
import { dummyFrame } from "../test/fixtures.js";

describe("halpe26", () => {
  it("swaps left and right keypoints", () => {
    const frame = dummyFrame();
    frame[5] = [10, 20, 0.9];
    frame[6] = [80, 20, 0.8];
    const swapped = swapLeftRight(frame);
    expect(swapped[5]).toEqual([80, 20, 0.8]);
    expect(swapped[6]).toEqual([10, 20, 0.9]);
    expect(frame[5]).toEqual([10, 20, 0.9]);
  });
});

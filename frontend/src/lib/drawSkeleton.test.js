import { describe, expect, it } from "vitest";

import { dummyFrame } from "../test/fixtures.js";
import { drawSkeleton, drawTrail } from "./drawSkeleton.js";
import { edgeSide, keypointSide } from "./halpe26.js";

function fakeCtx() {
  const calls = [];
  return {
    calls,
    save: () => calls.push(["save"]),
    restore: () => calls.push(["restore"]),
    beginPath: () => calls.push(["beginPath"]),
    moveTo: (x, y) => calls.push(["moveTo", x, y]),
    lineTo: (x, y) => calls.push(["lineTo", x, y]),
    stroke: () => calls.push(["stroke"]),
    fill: () => calls.push(["fill"]),
    arc: (x, y, r) => calls.push(["arc", x, y, r]),
    setLineDash: (dash) => calls.push(["setLineDash", dash]),
    clearRect: () => calls.push(["clearRect"]),
    strokeStyle: "",
    fillStyle: "",
    lineWidth: 0,
    globalAlpha: 1,
  };
}

describe("drawSkeleton", () => {
  it("draws bones and keypoints", () => {
    const ctx = fakeCtx();
    drawSkeleton(ctx, dummyFrame(), { srcWidth: 200, srcHeight: 200, dstWidth: 100, dstHeight: 100 });
    expect(ctx.calls.some((item) => item[0] === "stroke")).toBe(true);
    expect(ctx.calls.some((item) => item[0] === "arc")).toBe(true);
  });

  it("dashes low-confidence bones", () => {
    const ctx = fakeCtx();
    drawSkeleton(ctx, dummyFrame(0.1), { srcWidth: 200, srcHeight: 200, dstWidth: 100, dstHeight: 100, minScore: 0.3 });
    expect(ctx.calls.some((item) => item[0] === "setLineDash" && item[1][0] === 6)).toBe(true);
  });

  it("skips a missing frame", () => {
    const ctx = fakeCtx();
    drawSkeleton(ctx, null, {});
    expect(ctx.calls).toEqual([]);
  });

  it("draws a fading trail", () => {
    const ctx = fakeCtx();
    drawTrail(ctx, [dummyFrame(), dummyFrame()], { srcWidth: 200, srcHeight: 200, dstWidth: 100, dstHeight: 100 });
    expect(ctx.calls.filter((item) => item[0] === "stroke").length).toBeGreaterThan(1);
  });
});

describe("halpe26 sides", () => {
  it("marks left, right, and centre", () => {
    expect(keypointSide(5)).toBe("left");
    expect(keypointSide(6)).toBe("right");
    expect(keypointSide(18)).toBe("center");
    expect(edgeSide(5, 7)).toBe("left");
    expect(edgeSide(5, 6)).toBe("center");
  });
});

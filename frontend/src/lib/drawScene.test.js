import { describe, expect, it, vi } from "vitest";

import { drawSceneMarks } from "./drawScene.js";
import { sceneFixture } from "../test/fixtures.js";

function fakeCtx() {
  return {
    save: vi.fn(),
    restore: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    arc: vi.fn(),
  };
}

describe("drawSceneMarks", () => {
  it("draws a floor, zone, holds, and refs", () => {
    const ctx = fakeCtx();
    drawSceneMarks(ctx, sceneFixture, { srcWidth: 1920, srcHeight: 1080, dstWidth: 192, dstHeight: 108 });
    expect(ctx.stroke).toHaveBeenCalled();
    expect(ctx.fill).toHaveBeenCalled();
    expect(ctx.arc).toHaveBeenCalled();
  });
});

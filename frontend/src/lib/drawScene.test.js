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

  it("skips null zone, holds, and refs", () => {
    const ctx = fakeCtx();
    expect(() =>
      drawSceneMarks(
        ctx,
        {
          floor_line: [
            [0, 0],
            [720, 0],
          ],
          top_zone: null,
          start_holds: null,
          ref_points: null,
          source: "auto",
        },
        { srcWidth: 720, srcHeight: 1280, dstWidth: 72, dstHeight: 128 },
      ),
    ).not.toThrow();
    expect(ctx.stroke).toHaveBeenCalled();
    expect(ctx.arc).not.toHaveBeenCalled();
  });
});

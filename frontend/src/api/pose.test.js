import { describe, expect, it, vi } from "vitest";

import { getKeypoints, getPose } from "./pose.js";
import { jsonResponse } from "../test/mockApi.js";
import { keypointsFixture, poseFixture } from "../test/fixtures.js";

describe("pose api", () => {
  it("loads pose metadata and a keypoint window", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(poseFixture))
      .mockResolvedValueOnce(jsonResponse(keypointsFixture));
    await expect(getPose("vid-1")).resolves.toMatchObject({ climber_track_id: 1 });
    const keypoints = await getKeypoints("vid-1", { start: 0, end: 120 });
    expect(keypoints.frames).toHaveLength(120);
    expect(String(globalThis.fetch.mock.calls[1][0])).toContain("track=climber");
    expect(String(globalThis.fetch.mock.calls[1][0])).toContain("effective=true");
  });
});

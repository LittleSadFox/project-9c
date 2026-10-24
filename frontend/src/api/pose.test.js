import { describe, expect, it, vi } from "vitest";

import {
  createPoseEdit,
  deletePoseEdit,
  getKeypoints,
  getPersons,
  getPose,
  getReviewQueue,
  setClimber,
} from "./pose.js";
import { jsonResponse } from "../test/mockApi.js";
import { keypointsFixture, personsFixture, poseFixture, reviewQueueFixture } from "../test/fixtures.js";

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

  it("loads persons, queue, climber, and edits from the §9 contract", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(personsFixture))
      .mockResolvedValueOnce(jsonResponse(reviewQueueFixture))
      .mockResolvedValueOnce(jsonResponse({ climber_track_id: 2, job_id: "detect-3" }))
      .mockResolvedValueOnce(jsonResponse({ edit_id: "ed-1", frames: [12] }, 201))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(getPersons("vid-1", 12)).resolves.toHaveLength(2);
    expect(String(globalThis.fetch.mock.calls[0][0])).toContain("/pose/persons?frame=12");
    const queue = await getReviewQueue("vid-1");
    expect(queue[0]).toMatchObject({ kind: "lr_flip", frame: 12 });
    await setClimber("vid-1", { frame: 12, x: 410, y: 220 });
    expect(JSON.parse(globalThis.fetch.mock.calls[2][1].body)).toEqual({ frame: 12, x: 410, y: 220 });
    const edit = await createPoseEdit("vid-1", { kind: "confirm", frame: 12 });
    expect(edit.edit_id).toBe("ed-1");
    await deletePoseEdit("vid-1", "ed-1");
    expect(String(globalThis.fetch.mock.calls[4][0])).toBe("/api/videos/vid-1/pose/edits/ed-1");
  });
});

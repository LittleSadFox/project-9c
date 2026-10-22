import { describe, expect, it, vi } from "vitest";

import { createAttempt, createdAttemptId, listVideos, uploadVideo, videoFrameUrl, videoProxyUrl, videoThumbUrl } from "./videos.js";
import { installFetch, installXhr, jsonResponse } from "../test/mockApi.js";
import { videoFixture } from "../test/fixtures.js";

describe("videos api", () => {
  it("lists videos with the §9 query shape", async () => {
    const fetchMock = installFetch([
      {
        method: "GET",
        test: (path) => path.includes("/api/videos?"),
        body: { items: [videoFixture], total: 1 },
      },
    ]);
    const result = await listVideos({ boulder_id: "b1", sort: "-recorded_at", limit: 50, offset: 0 });
    expect(result.total).toBe(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("boulder_id=b1");
    expect(String(fetchMock.mock.calls[0][0])).toContain("sort=-recorded_at");
  });

  it("uploads with filename and last_modified query params", async () => {
    const calls = installXhr({ payload: { video: videoFixture, job_id: "job-1" } });
    const file = new File([new Uint8Array([9])], "climb.mov", { type: "video/quicktime", lastModified: Date.parse("2026-10-22T00:00:00Z") });
    const result = await uploadVideo(file, { boulder_id: "b1" });
    expect(result.job_id).toBe("job-1");
    const path = calls.find((item) => item[0] === "send")[2];
    expect(path).toContain("/api/videos/upload?");
    expect(path).toContain("filename=climb.mov");
    expect(path).toContain("boulder_id=b1");
    expect(path).toContain("last_modified=");
  });

  it("creates a missed attempt on the video", async () => {
    globalThis.fetch = vi.fn(async () => jsonResponse({ id: "att-1", start_frame: 10, end_frame: 40, outcome: "fall" }, 201));
    const result = await createAttempt("vid-1", { start_frame: 10, end_frame: 40, outcome: "fall" });
    expect(result.id).toBe("att-1");
    expect(result.attempt).toBeUndefined();
    const [path, options] = globalThis.fetch.mock.calls[0];
    expect(path).toBe("/api/videos/vid-1/attempts");
    expect(JSON.parse(options.body)).toEqual({ start_frame: 10, end_frame: 40, outcome: "fall" });
  });

  it("reads a flat create-attempt id and rejects a wrapped payload", () => {
    expect(createdAttemptId({ id: "att-1", start_frame: 10, outcome: "fall" })).toBe("att-1");
    expect(() => createdAttemptId({ attempt: { id: "att-1" }, job_id: "cut-1" })).toThrow(
      /flat attempt id/,
    );
  });

  it("builds media URLs from the contract", () => {
    expect(videoProxyUrl("vid-1")).toBe("/api/videos/vid-1/proxy");
    expect(videoThumbUrl("vid-1", 3)).toBe("/api/videos/vid-1/thumb?i=3");
    expect(videoFrameUrl("vid-1", 12, "original")).toBe("/api/videos/vid-1/frame?n=12&source=original");
  });
});

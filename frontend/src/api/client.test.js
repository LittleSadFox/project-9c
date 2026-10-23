import { describe, expect, it, vi } from "vitest";

import { ApiError, request, toQuery, uploadFile } from "./client.js";
import { installXhr, jsonResponse } from "../test/mockApi.js";

describe("toQuery", () => {
  it("omits empty values", () => {
    expect(toQuery({ q: "moon", boulder_id: "", limit: 50 })).toBe("?q=moon&limit=50");
    expect(toQuery({})).toBe("");
  });
});

describe("request", () => {
  it("parses the error envelope", async () => {
    globalThis.fetch = vi.fn(async () =>
      jsonResponse(
        { error: { code: "duplicate_video", message: "This video is already in the library.", details: { existing_video_id: "vid-1" } } },
        409,
      ),
    );
    await expect(request("/api/videos/upload")).rejects.toMatchObject({
      name: "ApiError",
      code: "duplicate_video",
      status: 409,
      details: { existing_video_id: "vid-1" },
    });
  });

  it("returns null for 204", async () => {
    globalThis.fetch = vi.fn(async () => new Response(null, { status: 204 }));
    await expect(request("/api/videos/vid-1", { method: "DELETE" })).resolves.toBeNull();
  });
});

describe("uploadFile", () => {
  it("sends an octet-stream body and reports progress", async () => {
    const calls = installXhr({
      status: 202,
      payload: { video: { id: "vid-1" }, job_id: "job-1" },
      progress: [0.5, 1],
    });
    const file = new File([new Uint8Array([1, 2, 3])], "clip.mov", { type: "video/quicktime" });
    const progress = [];
    const result = await uploadFile("/api/videos/upload?filename=clip.mov", file, (value) => progress.push(value));
    expect(result.job_id).toBe("job-1");
    expect(progress).toEqual([0.5, 1]);
    expect(calls).toContainEqual(["header", "Content-Type", "application/octet-stream"]);
  });

  it("throws ApiError on a failed upload", async () => {
    installXhr({
      status: 409,
      payload: { error: { code: "duplicate_video", message: "dup", details: { existing_video_id: "vid-1" } } },
    });
    await expect(uploadFile("/api/videos/upload", new File(["x"], "a.mov"))).rejects.toBeInstanceOf(ApiError);
  });
});

import { describe, expect, it, vi } from "vitest";

import { copySceneFrom, getScene, putScene, sceneWriteBody } from "./scene.js";
import { jsonResponse } from "../test/mockApi.js";
import { sceneFixture } from "../test/fixtures.js";

function assertWritableSceneBody(body) {
  expect(body).toEqual({
    floor_line: sceneFixture.floor_line,
    top_zone: sceneFixture.top_zone,
    start_holds: sceneFixture.start_holds,
    ref_points: sceneFixture.ref_points,
  });
  expect(body).not.toHaveProperty("source");
}

describe("scene api", () => {
  it("loads, replaces, and copies scene marks", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(sceneFixture))
      .mockResolvedValueOnce(jsonResponse({ scene: sceneFixture, job_id: "detect-1" }))
      .mockResolvedValueOnce(jsonResponse({ scene: sceneFixture, job_id: "detect-2" }));
    await expect(getScene("vid-1")).resolves.toMatchObject({ source: "auto" });
    const saved = await putScene("vid-1", sceneFixture);
    expect(saved.job_id).toBe("detect-1");
    expect(String(globalThis.fetch.mock.calls[1][0])).toBe("/api/videos/vid-1/scene");
    expect(globalThis.fetch.mock.calls[1][1].method).toBe("PUT");
    assertWritableSceneBody(JSON.parse(globalThis.fetch.mock.calls[1][1].body));
    await copySceneFrom("vid-1", "vid-2");
    expect(String(globalThis.fetch.mock.calls[2][0])).toBe(
      "/api/videos/vid-1/scene/copy-from/vid-2",
    );
  });

  it("strips source and other extras from the PUT body", async () => {
    globalThis.fetch = vi.fn().mockResolvedValueOnce(jsonResponse({ scene: sceneFixture, job_id: "detect-1" }));
    const getShaped = { ...sceneFixture, extra: "nope", updated_at: "2026-10-24T00:00:00Z" };
    expect(sceneWriteBody(getShaped)).not.toHaveProperty("source");
    await putScene("vid-1", getShaped);
    const body = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
    assertWritableSceneBody(body);
    expect(Object.keys(body).sort()).toEqual(["floor_line", "ref_points", "start_holds", "top_zone"]);
  });
});

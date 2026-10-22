import { describe, expect, it, vi } from "vitest";

import { attemptClipUrl, listAttempts, patchAttempt } from "./attempts.js";
import { jsonResponse } from "../test/mockApi.js";
import { attemptFixture } from "../test/fixtures.js";

describe("attempts api", () => {
  it("lists attempts for a boulder", async () => {
    globalThis.fetch = vi.fn(async () => jsonResponse({ items: [attemptFixture], total: 1 }));
    const result = await listAttempts({ boulder_id: "b1", rated: "false" });
    expect(result.items[0].id).toBe("att-1");
    expect(String(globalThis.fetch.mock.calls[0][0])).toContain("boulder_id=b1");
  });

  it("patches ratings as 0-10 integers", async () => {
    globalThis.fetch = vi.fn(async () => jsonResponse({ ...attemptFixture, proximity: 8 }));
    await patchAttempt("att-1", { proximity: 8, exertion: 2, outcome: "send", notes: "ok" });
    const body = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
    expect(body).toEqual({ proximity: 8, exertion: 2, outcome: "send", notes: "ok" });
  });

  it("builds a versioned clip URL", () => {
    expect(attemptClipUrl("att-1", 3)).toBe("/api/attempts/att-1/clip?v=3");
  });
});

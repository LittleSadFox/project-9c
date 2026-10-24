import { describe, expect, it, vi } from "vitest";

import { acceptProposal, batchAcceptProposals, listProposals, rejectProposal } from "./proposals.js";
import { jsonResponse } from "../test/mockApi.js";
import { attemptFixture, proposalFixture } from "../test/fixtures.js";

describe("proposals api", () => {
  it("lists proposals and posts accept, reject, and batch-accept", async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse([proposalFixture]))
      .mockResolvedValueOnce(jsonResponse({ attempt: attemptFixture, job_id: "cut-1" }, 201))
      .mockResolvedValueOnce(jsonResponse({ id: "prop-1", status: "rejected" }))
      .mockResolvedValueOnce(jsonResponse({ accepted: ["prop-1"] }));
    const items = await listProposals("vid-1");
    expect(items).toHaveLength(1);
    expect(String(globalThis.fetch.mock.calls[0][0])).toBe("/api/videos/vid-1/proposals");
    const accepted = await acceptProposal("prop-1", { start_frame: 12, end_frame: 40, outcome: "fall" });
    expect(accepted.attempt.id).toBe("att-1");
    expect(JSON.parse(globalThis.fetch.mock.calls[1][1].body).start_frame).toBe(12);
    await rejectProposal("prop-1", "not_attempt");
    expect(JSON.parse(globalThis.fetch.mock.calls[2][1].body).reason).toBe("not_attempt");
    await batchAcceptProposals(["prop-1", "prop-2"]);
    expect(JSON.parse(globalThis.fetch.mock.calls[3][1].body).ids).toEqual(["prop-1", "prop-2"]);
  });
});

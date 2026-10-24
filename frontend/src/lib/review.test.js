import { describe, expect, it } from "vitest";

import { proposalFixture, proposalTwoFixture } from "../test/fixtures.js";
import { acceptPayload, canFinishReview, nextPending } from "./review.js";

describe("review helpers", () => {
  it("walks to the next pending proposal", () => {
    const items = [proposalFixture, proposalTwoFixture];
    expect(nextPending(items, "prop-1").id).toBe("prop-2");
    expect(nextPending(items, "prop-2").id).toBe("prop-1");
    expect(nextPending([{ ...proposalFixture, status: "accepted" }], "prop-1")).toBeNull();
  });

  it("sends adjusted frames only when they change", () => {
    expect(acceptPayload(proposalFixture, 10, 40, "fall")).toEqual({ outcome: "fall" });
    expect(acceptPayload(proposalFixture, 12, 44, "send")).toEqual({
      start_frame: 12,
      end_frame: 44,
      outcome: "send",
    });
  });

  it("allows finish only when no pending remain", () => {
    expect(canFinishReview([proposalFixture], "unreviewed")).toBe(false);
    expect(canFinishReview([{ ...proposalFixture, status: "accepted" }], "unreviewed")).toBe(true);
    expect(canFinishReview([], "reviewed")).toBe(false);
  });
});

import { describe, expect, it } from "vitest";

import { asList, emptyScene, pendingProposals } from "./lists.js";

describe("lists", () => {
  it("reads a bare array or an items wrapper", () => {
    expect(asList([{ id: "a" }])).toEqual([{ id: "a" }]);
    expect(asList({ items: [{ id: "b" }], total: 1 })).toEqual([{ id: "b" }]);
    expect(asList(null)).toEqual([]);
  });

  it("keeps only pending proposals", () => {
    expect(
      pendingProposals([
        { id: "p1", status: "pending" },
        { id: "p2", status: "accepted" },
      ]),
    ).toEqual([{ id: "p1", status: "pending" }]);
  });

  it("returns an empty scene", () => {
    expect(emptyScene().floor_line).toEqual([]);
    expect(emptyScene().source).toBe("auto");
  });
});

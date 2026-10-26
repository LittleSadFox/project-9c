import { describe, expect, it } from "vitest";

import { asList, emptyScene, normalizeScene, pendingProposals } from "./lists.js";

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

  it("treats null scene arrays as empty lists", () => {
    const scene = normalizeScene({
      floor_line: [
        [0, 0],
        [720, 0],
      ],
      top_zone: null,
      start_holds: null,
      ref_points: null,
      source: "auto",
    });
    expect(scene.floor_line).toHaveLength(2);
    expect(scene.top_zone).toEqual([]);
    expect(scene.start_holds).toEqual([]);
    expect(scene.ref_points).toEqual([]);
    expect(normalizeScene(null).source).toBe("auto");
  });
});

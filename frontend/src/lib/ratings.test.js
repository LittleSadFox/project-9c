import { describe, expect, it } from "vitest";

import { changedRatings, ratingsFrom } from "./ratings.js";

describe("ratingsFrom", () => {
  it("keeps missing ratings as null", () => {
    expect(ratingsFrom({ outcome: "unknown" })).toEqual({
      outcome: "unknown",
      proximity: null,
      exertion: null,
      notes: "",
    });
  });

  it("keeps an explicit zero", () => {
    expect(ratingsFrom({ outcome: "fall", proximity: 0, exertion: 0, notes: "" })).toEqual({
      outcome: "fall",
      proximity: 0,
      exertion: 0,
      notes: "",
    });
  });
});

describe("changedRatings", () => {
  it("omits unrated scores when only notes change", () => {
    const current = { outcome: "unknown", proximity: null, exertion: null, notes: "" };
    const draft = { outcome: "unknown", proximity: null, exertion: null, notes: "heel hook" };
    expect(changedRatings(draft, current)).toEqual({ notes: "heel hook" });
  });

  it("sends only a moved slider", () => {
    const current = { outcome: "unknown", proximity: 3, exertion: 5, notes: "" };
    const draft = { outcome: "unknown", proximity: 9, exertion: 5, notes: "" };
    expect(changedRatings(draft, current)).toEqual({ proximity: 9 });
  });

  it("can send an explicit zero once the user rates", () => {
    const current = { outcome: "unknown", proximity: null, exertion: null, notes: "" };
    const draft = { outcome: "unknown", proximity: 0, exertion: null, notes: "" };
    expect(changedRatings(draft, current)).toEqual({ proximity: 0 });
  });
});

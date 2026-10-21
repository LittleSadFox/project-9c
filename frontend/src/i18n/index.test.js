import { describe, expect, it } from "vitest";

import { t } from "./index.js";

describe("t()", () => {
  it("returns English strings", () => {
    expect(t("brand")).toBe("Climbing Coach");
    expect(t("nav.library")).toBe("Library");
  });

  it("returns the key when a string is missing", () => {
    expect(t("missing.key")).toBe("missing.key");
  });
});

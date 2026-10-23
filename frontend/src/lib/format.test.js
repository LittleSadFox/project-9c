import { describe, expect, it } from "vitest";

import { formatBytes, formatFrameLabel, formatPercent, formatTimecode } from "./format.js";

describe("format", () => {
  it("formats a timecode from a frame", () => {
    expect(formatTimecode(90, 30)).toBe("00:03");
    expect(formatFrameLabel(90, 30)).toBe("00:03 · 90");
  });

  it("formats percents and bytes", () => {
    expect(formatPercent(0.42)).toBe("42%");
    expect(formatBytes(4096)).toBe("4.0 KB");
  });
});

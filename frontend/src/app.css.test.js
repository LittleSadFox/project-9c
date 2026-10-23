import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "app.css"), "utf8");

describe("app.css tokens", () => {
  it("uses only --lg-* tokens for colour, radius, and easing", () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/\brgba?\(/);
    expect(css).not.toMatch(/\bhsla?\(/);
    expect(css).not.toMatch(/border-radius\s*:\s*[0-9]/);
    expect(css).not.toMatch(/cubic-bezier\s*\(/);
  });

  it("keeps space between Library copy and the hint button", () => {
    expect(css).toMatch(/\.page-copy \+ \.hint\s*\{[^}]*margin-top:\s*var\(--lg-space-4\)/s);
  });
});

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const vite = readFileSync(join(here, "..", "vite.config.js"), "utf8");
const spec = readFileSync(join(here, "..", "e2e", "shell.spec.js"), "utf8");

describe("preview smoke stubs", () => {
  it("stubs /health and /api/jobs on the preview server", () => {
    expect(vite).toMatch(/configurePreviewServer/);
    expect(vite).toMatch(/path === "\/health"/);
    expect(vite).toMatch(/path === "\/api\/jobs"/);
    expect(vite).not.toMatch(/preview:\s*\{[^}]*proxy/s);
  });

  it("stubs those routes in the Playwright smoke test", () => {
    expect(spec).toMatch(/page\.route\("\*\*\/health"/);
    expect(spec).toMatch(/page\.route\("\*\*\/api\/jobs/);
  });
});

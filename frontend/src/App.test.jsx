import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App.jsx";

beforeEach(() => {
  globalThis.fetch = vi.fn(async (url) => {
    if (String(url).includes("/health")) {
      return new Response(JSON.stringify({ status: "ok", dev: false }), { status: 200 });
    }
    if (String(url).includes("/api/jobs")) {
      return new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
});

describe("App shell", () => {
  it("renders the brand and primary nav", async () => {
    render(<App />);
    expect(screen.getByText("Climbing Coach")).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Library" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Compare" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Library" })).toBeTruthy();
    expect(await screen.findByText("No videos yet. Import starts in Phase 1.")).toBeTruthy();
  });
});

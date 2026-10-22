import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { App } from "./App.jsx";
import { installFetch } from "./test/mockApi.js";

beforeEach(() => {
  installFetch([]);
});

describe("App shell", () => {
  it("renders the brand and primary nav", async () => {
    render(<App />);
    expect(screen.getByText("Climbing Coach")).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Library" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Compare" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Library" })).toBeTruthy();
    expect(await screen.findByText("No videos yet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Import" })).toBeTruthy();
  });
});

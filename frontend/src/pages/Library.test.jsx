import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { LibraryPage } from "./Library.jsx";
import { boulderFixture, sessionFixture, videoFixture } from "../test/fixtures.js";
import { installFetch, installXhr } from "../test/mockApi.js";

function renderLibrary(path = "/library") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/library/boulders/:boulderId" element={<LibraryPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LibraryPage", () => {
  it("renders filters, videos, and the import action", async () => {
    installFetch([
      { method: "GET", test: (path) => path.startsWith("/api/boulders"), body: { items: [boulderFixture], total: 1 } },
      { method: "GET", test: (path) => path.startsWith("/api/sessions"), body: { items: [sessionFixture], total: 1 } },
      { method: "GET", test: (path) => path.startsWith("/api/videos"), body: { items: [videoFixture], total: 1 } },
    ]);
    renderLibrary();
    expect(screen.getByRole("heading", { name: "Library" })).toBeTruthy();
    expect(await screen.findByText("The Wave")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Needs review" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Unsorted" })).toBeTruthy();
    expect(await screen.findByText("session.mov")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Import" })).toBeTruthy();
  });

  it("uploads a dropped file and shows progress", async () => {
    installFetch([
      { method: "GET", test: (path) => path.startsWith("/api/boulders"), body: { items: [boulderFixture], total: 1 } },
      { method: "GET", test: (path) => path.startsWith("/api/videos"), body: { items: [videoFixture], total: 1 } },
    ]);
    installXhr({ payload: { video: videoFixture, job_id: "job-1" } });
    renderLibrary();
    await screen.findByText("session.mov");
    const file = new File([new Uint8Array([1, 2])], "new.mov", { type: "video/quicktime" });
    fireEvent.drop(document.querySelector(".drop-zone"), {
      dataTransfer: { files: [file] },
    });
    await waitFor(() => expect(screen.getByText("new.mov")).toBeTruthy());
    await waitFor(() => expect(screen.getByText("100%")).toBeTruthy());
  });

  it("shows a duplicate upload error from the envelope", async () => {
    installFetch([
      { method: "GET", test: (path) => path.startsWith("/api/videos"), body: { items: [], total: 0 } },
    ]);
    installXhr({
      status: 409,
      payload: {
        error: {
          code: "duplicate_video",
          message: "This video is already in the library.",
          details: { existing_video_id: "vid-1" },
        },
      },
    });
    renderLibrary();
    await screen.findByText("No videos yet.");
    fireEvent.drop(document.querySelector(".drop-zone"), {
      dataTransfer: { files: [new File(["x"], "dup.mov")] },
    });
    expect(await screen.findByText("Already in the library.")).toBeTruthy();
  });

  it("creates a boulder from the sheet", async () => {
    const fetchMock = installFetch([
      { method: "GET", test: (path) => path.startsWith("/api/boulders"), body: { items: [], total: 0 } },
      { method: "POST", test: (path) => path === "/api/boulders", body: { id: "b2", name: "Moon" }, status: 201 },
    ]);
    renderLibrary();
    fireEvent.click(screen.getByRole("button", { name: "New boulder" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Moon" } });
    fireEvent.click(screen.getByRole("button", { name: "Create boulder" }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((call) => call[1] && call[1].method === "POST");
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toMatchObject({ name: "Moon" });
    });
  });
});

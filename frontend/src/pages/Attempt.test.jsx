import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { AttemptPage } from "./Attempt.jsx";
import { attemptFixture, keypointsFixture, poseFixture, videoFixture } from "../test/fixtures.js";
import { installFetch } from "../test/mockApi.js";

function renderAttempt() {
  return render(
    <MemoryRouter initialEntries={["/attempts/att-1"]}>
      <Routes>
        <Route path="/attempts/:attemptId" element={<AttemptPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AttemptPage", () => {
  it("autosaves a rating change", async () => {
    const fetchMock = installFetch([
      { method: "GET", test: (path) => path === "/api/attempts/att-1", body: attemptFixture },
      { method: "GET", test: (path) => path === "/api/videos/vid-1", body: videoFixture },
      { method: "GET", test: (path) => path === "/api/videos/vid-1/pose", body: poseFixture },
      { method: "GET", test: (path) => path.includes("/pose/keypoints"), body: keypointsFixture },
      { method: "PATCH", test: (path) => path === "/api/attempts/att-1", body: { ...attemptFixture, proximity: 9 } },
    ]);
    renderAttempt();
    expect(await screen.findByText("Rating")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Proximity"), { target: { value: "9" } });
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find((call) => call[1] && call[1].method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse(patch[1].body)).toEqual({ proximity: 9 });
    });
  });

  it("does not mark an unrated attempt as 0/0 when only notes change", async () => {
    const unrated = { ...attemptFixture, proximity: null, exertion: null, rated_at: null, notes: "" };
    const fetchMock = installFetch([
      { method: "GET", test: (path) => path === "/api/attempts/att-1", body: unrated },
      { method: "GET", test: (path) => path === "/api/videos/vid-1", body: videoFixture },
      { method: "GET", test: (path) => path === "/api/videos/vid-1/pose", body: poseFixture },
      { method: "GET", test: (path) => path.includes("/pose/keypoints"), body: keypointsFixture },
      { method: "PATCH", test: (path) => path === "/api/attempts/att-1", body: { ...unrated, notes: "heel hook" } },
    ]);
    renderAttempt();
    expect(await screen.findByText("Rating")).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "heel hook" } });
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find((call) => call[1] && call[1].method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse(patch[1].body)).toEqual({ notes: "heel hook" });
    });
  });

  it("shows a clip-pending notice", async () => {
    installFetch([
      {
        method: "GET",
        test: (path) => path === "/api/attempts/att-1",
        body: { ...attemptFixture, clip_status: "running", clip_url: null },
      },
      { method: "GET", test: (path) => path === "/api/videos/vid-1", body: videoFixture },
    ]);
    renderAttempt();
    expect(await screen.findByText("The clip is still rendering.")).toBeTruthy();
  });
});

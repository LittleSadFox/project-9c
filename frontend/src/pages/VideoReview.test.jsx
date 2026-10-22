import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { AttemptPage } from "./Attempt.jsx";
import { VideoReviewPage } from "./VideoReview.jsx";
import { attemptFixture, keypointsFixture, poseFixture, videoFixture } from "../test/fixtures.js";
import { installFetch } from "../test/mockApi.js";

function renderReview() {
  return render(
    <MemoryRouter initialEntries={["/videos/vid-1"]}>
      <Routes>
        <Route path="/videos/:videoId" element={<VideoReviewPage />} />
        <Route path="/attempts/:attemptId" element={<AttemptPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function installReviewApi(extra = []) {
  return installFetch([
    { method: "GET", test: (path) => path === "/api/videos/vid-1", body: videoFixture },
    { method: "GET", test: (path) => path === "/api/videos/vid-1/pose", body: poseFixture },
    { method: "GET", test: (path) => path.includes("/pose/keypoints"), body: keypointsFixture },
    {
      method: "POST",
      test: (path) => path === "/api/videos/vid-1/attempts",
      status: 201,
      body: (path, options) => {
        const body = JSON.parse(options.body);
        return { attempt: { ...attemptFixture, ...body }, job_id: "cut-1" };
      },
    },
    { method: "GET", test: (path) => path === "/api/attempts/att-1", body: attemptFixture },
    { method: "GET", test: (path) => path === "/api/videos/vid-1", body: videoFixture },
    ...extra,
  ]);
}

describe("VideoReviewPage", () => {
  it("creates an attempt from in and out points", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    expect(await screen.findByRole("button", { name: "Create attempt" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "i" });
    fireEvent.keyDown(window, { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.click(screen.getByRole("button", { name: "Fall" }));
    fireEvent.click(screen.getByRole("button", { name: "Create attempt" }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/attempts"));
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body).outcome).toBe("fall");
      expect(JSON.parse(post[1].body).end_frame).toBeGreaterThan(JSON.parse(post[1].body).start_frame);
    });
    expect(await screen.findByText("Rating")).toBeTruthy();
  });

  it("creates an attempt with Enter", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: "Create attempt" });
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/attempts"))).toBe(true);
    });
  });
});

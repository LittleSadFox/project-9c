import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";

import { VideoReviewPage } from "./VideoReview.jsx";
import {
  attemptFixture,
  keypointsFixture,
  personsFixture,
  poseEditFixture,
  poseFixture,
  proposalFixture,
  proposalTwoFixture,
  reviewQueueFixture,
  sceneFixture,
  videoFixture,
} from "../test/fixtures.js";
import { installFetch } from "../test/mockApi.js";

function renderReview() {
  return render(
    <MemoryRouter initialEntries={["/videos/vid-1"]}>
      <Routes>
        <Route path="/videos/:videoId" element={<VideoReviewPage />} />
        <Route path="/library" element={<h1>Library</h1>} />
      </Routes>
    </MemoryRouter>,
  );
}

function videoPayload(extra = {}) {
  return {
    ...videoFixture,
    detect_status: "done",
    stages: { ingest: "done", pose: "done", detect: "done" },
    counts: { pending_proposals: 2, attempts: 1 },
    ...extra,
  };
}

function installReviewApi(extra = []) {
  const proposals = [structuredClone(proposalFixture), structuredClone(proposalTwoFixture)];
  return installFetch([
    { method: "GET", test: (path) => path === "/api/videos/vid-1", body: () => videoPayload() },
    { method: "GET", test: (path) => path === "/api/videos/vid-1/pose", body: poseFixture },
    { method: "GET", test: (path) => path.includes("/pose/keypoints"), body: keypointsFixture },
    { method: "GET", test: (path) => path === "/api/videos/vid-1/scene", body: sceneFixture },
    { method: "GET", test: (path) => path === "/api/videos/vid-1/proposals", body: () => proposals },
    { method: "GET", test: (path) => path === "/api/videos/vid-1/pose/review-queue", body: reviewQueueFixture },
    { method: "GET", test: (path) => path.includes("/pose/persons"), body: personsFixture },
    { method: "GET", test: (path) => path.startsWith("/api/videos?"), body: { items: [videoPayload({ id: "vid-2", original_name: "other.mov" })], total: 1 } },
    {
      method: "POST",
      test: (path) => path.endsWith("/accept"),
      status: 201,
      body: (path, options) => {
        const id = path.split("/")[3];
        const item = proposals.find((proposal) => proposal.id === id);
        if (item) {
          item.status = "accepted";
          item.attempt_id = "att-1";
        }
        return { attempt: { ...attemptFixture, ...JSON.parse(options.body || "{}") }, job_id: "cut-1" };
      },
    },
    {
      method: "POST",
      test: (path) => path.endsWith("/reject"),
      body: (path) => {
        const id = path.split("/")[3];
        const item = proposals.find((proposal) => proposal.id === id);
        if (item) {
          item.status = "rejected";
        }
        return { id, status: "rejected" };
      },
    },
    {
      method: "POST",
      test: (path) => path === "/api/proposals/batch-accept",
      body: (path, options) => {
        const ids = JSON.parse(options.body).ids || [];
        for (const id of ids) {
          const item = proposals.find((proposal) => proposal.id === id);
          if (item) {
            item.status = "accepted";
          }
        }
        return { accepted: ids };
      },
    },
    {
      method: "POST",
      test: (path) => path === "/api/videos/vid-1/attempts",
      status: 201,
      body: (path, options) => ({ ...attemptFixture, ...JSON.parse(options.body) }),
    },
    {
      method: "PATCH",
      test: (path) => path === "/api/videos/vid-1",
      body: (path, options) => videoPayload({ ...JSON.parse(options.body), counts: { pending_proposals: 0, attempts: 2 } }),
    },
    {
      method: "PUT",
      test: (path) => path === "/api/videos/vid-1/scene",
      body: (path, options) => ({ scene: { ...JSON.parse(options.body), source: "user" }, job_id: "detect-1" }),
    },
    {
      method: "POST",
      test: (path) => path.includes("/scene/copy-from/"),
      body: { scene: sceneFixture, job_id: "detect-2" },
    },
    {
      method: "POST",
      test: (path) => path === "/api/videos/vid-1/pose/edits",
      status: 201,
      body: poseEditFixture,
    },
    { method: "DELETE", test: (path) => path.includes("/pose/edits/"), body: null, status: 204 },
    {
      method: "PUT",
      test: (path) => path === "/api/videos/vid-1/pose/climber",
      body: { climber_track_id: 2, job_id: "detect-3" },
    },
    ...extra,
  ]);
}

describe("VideoReviewPage", () => {
  it("accepts the selected proposal with Enter", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    expect(await screen.findByRole("button", { name: "Finish review" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: /10–40/ })).toBeTruthy();
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/proposals/prop-1/accept"));
      expect(post).toBeTruthy();
    });
  });

  it("rejects the selected proposal with Delete", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: /10–40/ });
    fireEvent.keyDown(window, { key: "Delete" });
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/proposals/prop-1/reject"));
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body).reason).toBe("not_attempt");
    });
  });

  it("adjusts in and out with I/O then accepts the new frames", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: /10–40/ });
    fireEvent.keyDown(window, { key: "i" });
    fireEvent.keyDown(window, { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(window, { key: "o" });
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/proposals/prop-1/accept"));
      expect(post).toBeTruthy();
      const body = JSON.parse(post[1].body);
      expect(body.end_frame).toBeGreaterThan(body.start_frame || 10);
    });
  });

  it("batch-accepts the checked proposals", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: "Accept selected" });
    fireEvent.click(screen.getByLabelText("Select prop-1"));
    fireEvent.click(screen.getByRole("button", { name: "Accept selected" }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/proposals/batch-accept"));
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body).ids).toContain("prop-1");
    });
  });

  it("adds a missed attempt from the current in and out", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: "Add missed" });
    fireEvent.click(screen.getByRole("button", { name: "Add missed" }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (call) => String(call[0]).endsWith("/videos/vid-1/attempts") && call[1] && call[1].method === "POST",
      );
      expect(post).toBeTruthy();
      const body = JSON.parse(post[1].body);
      expect(body.start_frame).toBeDefined();
      expect(body.end_frame).toBeGreaterThan(body.start_frame);
    });
  });

  it("finishes review when no pending proposals remain", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: "Finish review" });
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/proposals/prop-1/accept"))).toBe(true);
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Accept attempt" }).disabled).toBe(false);
    });
    fireEvent.keyDown(window, { key: "Enter" });
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/proposals/prop-2/accept"))).toBe(true);
    });
    const finish = screen.getByRole("button", { name: "Finish review" });
    await waitFor(() => expect(finish.disabled).toBe(false));
    fireEvent.click(finish);
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(
        (call) => String(call[0]) === "/api/videos/vid-1" && call[1] && call[1].method === "PATCH",
      );
      expect(patch).toBeTruthy();
      expect(JSON.parse(patch[1].body).review_status).toBe("reviewed");
    });
  });

  it("does not accept when a button is focused", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    const finish = await screen.findByRole("button", { name: "Finish review" });
    finish.focus();
    fireEvent.keyDown(finish, { key: "Enter" });
    fireEvent.keyDown(finish, { key: "Delete" });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/accept"))).toBe(false);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/reject"))).toBe(false);
  });

  it("does not accept when a link is focused", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: "Finish review" });
    const link = screen.getByRole("link", { name: "Library" });
    link.focus();
    fireEvent.keyDown(link, { key: "Enter" });
    fireEvent.keyDown(link, { key: "Delete" });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/accept"))).toBe(false);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/reject"))).toBe(false);
  });

  it("does not accept or reject while a confirm sheet is open", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: "Finish review" });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByRole("dialog", { name: "Reject proposal" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "Enter" });
    fireEvent.keyDown(window, { key: "Delete" });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/accept"))).toBe(false);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/reject"))).toBe(false);
  });

  it("opens the skeleton editor with E and confirms a frame", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: "Finish review" });
    fireEvent.keyDown(window, { key: "e" });
    expect(await screen.findByRole("application", { name: "Skeleton stage" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Confirm frame" }));
    await waitFor(() => {
      const post = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/pose/edits"));
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body).kind).toBe("confirm");
    });
  });

  it("saves scene marks and copies from another video", async () => {
    const fetchMock = installReviewApi();
    renderReview();
    await screen.findByRole("button", { name: "Save marks" });
    fireEvent.click(screen.getByRole("button", { name: "Save marks" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => String(call[0]).endsWith("/scene") && call[1]?.method === "PUT")).toBe(
        true,
      );
    });
    const savePut = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/scene") && call[1]?.method === "PUT");
    const saveBody = JSON.parse(savePut[1].body);
    expect(saveBody).not.toHaveProperty("source");
    expect(Object.keys(saveBody).sort()).toEqual(["floor_line", "ref_points", "start_holds", "top_zone"]);
    fireEvent.change(screen.getByLabelText("Copy from"), { target: { value: "vid-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Copy marks" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/scene/copy-from/vid-2"))).toBe(true);
    });
  });

  it("jumps from the skeleton queue", async () => {
    installReviewApi();
    renderReview();
    fireEvent.click(await screen.findByRole("button", { name: /Frame 40/ }));
    expect(await screen.findByRole("application", { name: "Skeleton stage" })).toBeTruthy();
  });
});

import { expect, test } from "@playwright/test";

const video = {
  id: "vid-1",
  original_name: "fixture.mov",
  fps: 30,
  proxy_fps: 30,
  n_frames: 120,
  proxy_width: 1920,
  proxy_height: 1080,
  ingest_status: "done",
  pose_status: "done",
  detect_status: "done",
  review_status: "unreviewed",
  boulder_id: "b1",
  stages: { ingest: "done", pose: "done", detect: "done" },
  counts: { pending_proposals: 2, attempts: 0 },
};

const proposals = [
  {
    id: "prop-1",
    start_frame: 10,
    end_frame: 40,
    outcome_guess: "fall",
    confidence: 0.8,
    model_version: "event/rule-v1",
    status: "pending",
    attempt_id: null,
  },
  {
    id: "prop-2",
    start_frame: 60,
    end_frame: 90,
    outcome_guess: "send",
    confidence: 0.7,
    model_version: "event/rule-v1",
    status: "pending",
    attempt_id: null,
  },
];

const empty = { items: [], total: 0 };

async function json(route, body, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

test("reviews a whole fixture video keyboard-only against mocked D+E APIs", async ({ page }) => {
  proposals[0].status = "pending";
  proposals[1].status = "pending";
  video.review_status = "unreviewed";
  video.counts.pending_proposals = 2;

  await page.route("**/health", (route) =>
    json(route, {
      status: "ok",
      version: "0",
      db: "ok",
      ffmpeg: { version: "7", h264_encoder: "stub" },
      onnx: { providers: ["CPUExecutionProvider"], device: "cpu" },
      library_free_gb: 1,
      dev: false,
    }),
  );
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (path === "/api/jobs") {
      await json(route, empty);
      return;
    }
    if (path === "/api/videos/vid-1/proposals") {
      await json(route, proposals);
      return;
    }
    if (path === "/api/proposals/prop-1/accept" && method === "POST") {
      proposals[0].status = "accepted";
      await json(route, { attempt: { id: "att-1" }, job_id: "cut-1" }, 201);
      return;
    }
    if (path === "/api/proposals/prop-2/accept" && method === "POST") {
      proposals[1].status = "accepted";
      await json(route, { attempt: { id: "att-2" }, job_id: "cut-2" }, 201);
      return;
    }
    if (path === "/api/videos/vid-1" && method === "PATCH") {
      video.review_status = "reviewed";
      video.counts.pending_proposals = 0;
      await json(route, video);
      return;
    }
    if (path === "/api/videos/vid-1") {
      await json(route, video);
      return;
    }
    if (path === "/api/videos/vid-1/pose") {
      await json(route, { climber_track_id: 1, edges: [], tracks: [] });
      return;
    }
    if (path === "/api/videos/vid-1/pose/keypoints") {
      await json(route, { start: 0, end: 120, frames: [] });
      return;
    }
    if (path === "/api/videos/vid-1/pose/review-queue") {
      await json(route, []);
      return;
    }
    if (path === "/api/videos/vid-1/pose/persons") {
      await json(route, []);
      return;
    }
    if (path === "/api/videos/vid-1/scene") {
      await json(route, {
        floor_line: [
          [0, 1000],
          [1900, 1000],
        ],
        top_zone: [
          [700, 40],
          [1200, 40],
          [1200, 160],
          [700, 160],
        ],
        start_holds: [],
        ref_points: [],
        source: "auto",
      });
      return;
    }
    if (path.startsWith("/api/videos/vid-1/proxy") || path.startsWith("/api/videos/vid-1/thumb") || path.startsWith("/api/videos/vid-1/frame")) {
      await route.fulfill({ status: 204 });
      return;
    }
    await json(route, empty);
  });

  await page.goto("/videos/vid-1");
  await expect(page.getByRole("button", { name: "Finish review" })).toBeVisible();
  await expect(page.getByRole("button", { name: /10–40/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Accepted").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept attempt" })).toBeEnabled();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Accepted").nth(1)).toBeVisible();
  const finish = page.getByRole("button", { name: "Finish review" });
  await expect(finish).toBeEnabled();
  await finish.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("This video is reviewed.")).toBeVisible();
});

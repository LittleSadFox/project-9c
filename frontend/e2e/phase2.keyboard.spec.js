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

  await page.route("**/api/boulders**", (route) => json(route, empty));
  await page.route("**/api/sessions**", (route) => json(route, empty));
  await page.route("**/api/attempts**", (route) => json(route, empty));
  await page.route("**/api/trash**", (route) => json(route, empty));
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
  await page.route("**/api/jobs**", (route) => json(route, empty));
  await page.route("**/api/videos/vid-1/pose/keypoints**", (route) =>
    json(route, { start: 0, end: 120, frames: [] }),
  );
  await page.route("**/api/videos/vid-1/pose/review-queue", (route) => json(route, []));
  await page.route("**/api/videos/vid-1/pose/persons**", (route) => json(route, []));
  await page.route("**/api/videos/vid-1/pose", (route) =>
    json(route, { climber_track_id: 1, edges: [], tracks: [] }),
  );
  await page.route("**/api/videos/vid-1/scene", async (route) => {
    if (route.request().method() === "PUT") {
      await json(route, { scene: {}, job_id: "detect-1" });
      return;
    }
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
  });
  await page.route("**/api/videos/vid-1/proposals", (route) => json(route, proposals));
  await page.route("**/api/proposals/prop-1/accept", async (route) => {
    proposals[0].status = "accepted";
    await json(route, { attempt: { id: "att-1" }, job_id: "cut-1" }, 201);
  });
  await page.route("**/api/proposals/prop-2/accept", async (route) => {
    proposals[1].status = "accepted";
    await json(route, { attempt: { id: "att-2" }, job_id: "cut-2" }, 201);
  });
  await page.route("**/api/videos/vid-1", async (route) => {
    if (route.request().method() === "PATCH") {
      video.review_status = "reviewed";
      video.counts.pending_proposals = 0;
      await json(route, video);
      return;
    }
    await json(route, video);
  });
  await page.goto("/videos/vid-1");
  await expect(page.getByRole("button", { name: "Finish review" })).toBeVisible();
  await expect(page.getByRole("button", { name: /10–40/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Enter");
  const finish = page.getByRole("button", { name: "Finish review" });
  await expect(finish).toBeEnabled();
  await finish.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("This video is reviewed.")).toBeVisible();
});

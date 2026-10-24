export const boulderFixture = {
  id: "b1",
  name: "The Wave",
  gym: "Kilter",
  grade: "V5",
  status: "active",
  video_count: 1,
  attempt_count: 1,
  sent: false,
  best_proximity: 3,
  last_attempt_at: "2026-10-22T00:00:00Z",
};

export const sessionFixture = {
  id: "s1",
  date: "2026-10-22",
  gym: "Kilter",
};

export const videoFixture = {
  id: "vid-1",
  original_name: "session.mov",
  fps: 30,
  proxy_fps: 30,
  n_frames: 120,
  proxy_width: 1920,
  proxy_height: 1080,
  ingest_status: "done",
  pose_status: "done",
  detect_status: "pending",
  review_status: "unreviewed",
  size_bytes: 4096,
  boulder_id: "b1",
  session_id: "s1",
  stages: { ingest: "done", pose: "done", detect: "pending" },
  counts: { pending_proposals: 0, attempts: 1 },
};

export const attemptFixture = {
  id: "att-1",
  video_id: "vid-1",
  boulder_id: "b1",
  start_frame: 10,
  end_frame: 40,
  outcome: "unknown",
  proximity: 3,
  exertion: 5,
  notes: "",
  fps: 30,
  duration_s: 1,
  clip_url: "/api/attempts/att-1/clip?v=1",
  clip_status: "done",
  clip_version: 1,
};

export const poseFixture = {
  run_id: "run-1",
  model_version: "pose/base",
  provider: "CPUExecutionProvider",
  fps: 30,
  n_frames: 120,
  keypoint_names: [],
  edges: [
    [5, 7],
    [7, 9],
  ],
  climber_track_id: 1,
  tracks: [{ track_id: 1, first_frame: 0, last_frame: 119, coverage: 1, vertical_travel: 12 }],
};

export function dummyFrame(score = 0.9) {
  return Array.from({ length: 26 }, (_, index) => [100 + index, 180 + index, score]);
}

export const keypointsFixture = {
  start: 0,
  end: 120,
  frames: Array.from({ length: 120 }, () => dummyFrame()),
};

export const sceneFixture = {
  floor_line: [
    [100, 980],
    [1800, 990],
  ],
  top_zone: [
    [700, 40],
    [1200, 40],
    [1200, 180],
    [700, 180],
  ],
  start_holds: [[900, 420]],
  ref_points: [{ name: "arete", x: 200, y: 300 }],
  source: "auto",
};

export const proposalFixture = {
  id: "prop-1",
  start_frame: 10,
  end_frame: 40,
  outcome_guess: "fall",
  confidence: 0.82,
  model_version: "event/rule-v1",
  status: "pending",
  attempt_id: null,
};

export const proposalTwoFixture = {
  id: "prop-2",
  start_frame: 60,
  end_frame: 90,
  outcome_guess: "send",
  confidence: 0.74,
  model_version: "event/rule-v1",
  status: "pending",
  attempt_id: null,
};

export const reviewQueueFixture = [
  { frame: 12, kind: "lr_flip", score: 0.21 },
  { frame: 40, kind: "low_score", score: 0.18 },
];

export const personsFixture = [
  {
    track_id: 1,
    bbox: [80, 100, 120, 240],
    keypoints: dummyFrame(),
  },
  {
    track_id: 2,
    bbox: [400, 160, 90, 200],
    keypoints: dummyFrame(0.4),
  },
];

export const poseEditFixture = {
  edit_id: "ed-1",
  frames: [12],
};

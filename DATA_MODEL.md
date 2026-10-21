# Data model

SQLite holds the library metadata.
IDs are UUID text.
Times are ISO 8601 UTC.
Frames are proxy frame indices.

Use the stdlib `sqlite3` module.
Turn on WAL mode.
Turn on foreign keys.
Set `busy_timeout=5000`.

Apply numbered `.sql` migrations.
Record applied versions in `schema_migrations`.

Write in ASD-STE100 Simplified Technical English.

## Conventions

- Primary keys are `id TEXT`.
- Foreign keys use the same UUID text.
- File names never come from user input.
- The original file name lives only in `videos.original_name`.
- Pose arrays live in NPZ files, not in this database.
- Learned models are ONNX plus JSON on disk.
  The database stores only the registry row.

## `boulders`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `name` | TEXT NOT NULL | |
| `gym` | TEXT | |
| `grade` | TEXT | |
| `color` | TEXT | |
| `sector` | TEXT | |
| `set_date` | TEXT | ISO date |
| `status` | TEXT NOT NULL | `active` or `archived` |
| `notes` | TEXT | |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `sessions`

The app creates one session per recording day.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `date` | TEXT NOT NULL | Recording day |
| `gym` | TEXT | |
| `notes` | TEXT | |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `videos`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `boulder_id` | TEXT | FK `boulders.id`, nullable |
| `session_id` | TEXT | FK `sessions.id`, nullable |
| `original_name` | TEXT NOT NULL | Display name only |
| `original_ext` | TEXT NOT NULL | |
| `sha256` | TEXT NOT NULL UNIQUE | Duplicate import key |
| `size_bytes` | INTEGER NOT NULL | |
| `duration_s` | REAL | |
| `src_fps` | REAL | |
| `is_vfr` | INTEGER NOT NULL | 0 or 1 |
| `src_width` | INTEGER | |
| `src_height` | INTEGER | |
| `rotation` | INTEGER | Source display rotation |
| `codec` | TEXT | |
| `recorded_at` | TEXT | ISO 8601 UTC |
| `proxy_fps` | REAL | Canonical fps |
| `proxy_width` | INTEGER | |
| `proxy_height` | INTEGER | |
| `n_frames` | INTEGER | Proxy frame count |
| `ingest_status` | TEXT NOT NULL | |
| `pose_status` | TEXT NOT NULL | |
| `detect_status` | TEXT NOT NULL | |
| `review_status` | TEXT NOT NULL | `unreviewed` or `reviewed` |
| `error` | TEXT | Last job error |
| `notes` | TEXT | |
| `deleted_at` | TEXT | Soft delete |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

Only a fully reviewed video may supply "not an attempt" labels.

## `pose_runs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `video_id` | TEXT NOT NULL | FK `videos.id` |
| `model_version_id` | TEXT | FK `model_versions.id` |
| `device` | TEXT | `cuda`, `mps`, or `cpu` |
| `provider` | TEXT | ONNX Runtime provider name |
| `mode` | TEXT | Pose mode |
| `det_every` | INTEGER | Detector stride |
| `fps_measured` | REAL | |
| `climber_track_id` | INTEGER | Selected track |
| `status` | TEXT NOT NULL | |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `pose_tracks`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `run_id` | TEXT NOT NULL | FK `pose_runs.id` |
| `track_id` | INTEGER NOT NULL | Tracker id |
| `first_frame` | INTEGER NOT NULL | |
| `last_frame` | INTEGER NOT NULL | |
| `coverage` | REAL | |
| `vertical_travel` | REAL | |
| `is_climber` | INTEGER NOT NULL | 0 or 1 |

## `pose_edits`

Edits apply to the climber track.
They survive a pose re-run.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `video_id` | TEXT NOT NULL | FK `videos.id` |
| `kind` | TEXT NOT NULL | `move`, `lr_swap`, `invalid`, `confirm` |
| `frame` | INTEGER NOT NULL | |
| `kpt` | INTEGER | Keypoint index |
| `x` | REAL | Proxy pixels |
| `y` | REAL | Proxy pixels |
| `range_start` | INTEGER | Inclusive |
| `range_end` | INTEGER | Inclusive |
| `undone_at` | TEXT | Null when active |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `scene_marks`

Scene marks are per video.
The camera moves between sessions.

| Column | Type | Notes |
| --- | --- | --- |
| `video_id` | TEXT PK | FK `videos.id` |
| `floor_line` | TEXT | JSON `[[x, y], [x, y]]` |
| `top_zone` | TEXT | JSON polygon |
| `start_holds` | TEXT | JSON points |
| `ref_points` | TEXT | JSON `[{name, x, y}]` |
| `source` | TEXT NOT NULL | `auto` or `user` |
| `updated_at` | TEXT NOT NULL | ISO 8601 UTC |

## `events`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `video_id` | TEXT NOT NULL | FK `videos.id` |
| `run_id` | TEXT | Detect job / pose run |
| `frame` | INTEGER NOT NULL | |
| `kind` | TEXT NOT NULL | `leave_ground`, `top`, `drop`, `ground_return` |
| `confidence` | REAL | |
| `source` | TEXT NOT NULL | `rule`, `model`, or `user` |
| `model_version_id` | TEXT | FK `model_versions.id` |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `proposals`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `video_id` | TEXT NOT NULL | FK `videos.id` |
| `start_frame` | INTEGER NOT NULL | |
| `end_frame` | INTEGER NOT NULL | |
| `outcome_guess` | TEXT | `send`, `fall`, or `unknown` |
| `confidence` | REAL | |
| `model_version_id` | TEXT | FK `model_versions.id` |
| `status` | TEXT NOT NULL | `pending`, `accepted`, `rejected`, `superseded` |
| `attempt_id` | TEXT | FK `attempts.id` after accept |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `attempts`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `video_id` | TEXT NOT NULL | FK `videos.id` |
| `boulder_id` | TEXT | FK `boulders.id` |
| `proposal_id` | TEXT | FK `proposals.id` |
| `start_frame` | INTEGER NOT NULL | |
| `end_frame` | INTEGER NOT NULL | |
| `outcome` | TEXT NOT NULL | `send`, `fall`, or `unknown` |
| `proximity` | INTEGER | 0–10 |
| `exertion` | INTEGER | 0–10 |
| `notes` | TEXT | |
| `rated_at` | TEXT | ISO 8601 UTC |
| `clip_version` | INTEGER NOT NULL | Clip URL cache buster |
| `clip_status` | TEXT NOT NULL | |
| `deleted_at` | TEXT | Soft delete |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `comparisons`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `attempt_a` | TEXT NOT NULL | FK `attempts.id` |
| `attempt_b` | TEXT NOT NULL | FK `attempts.id` |
| `params` | TEXT | JSON alignment params |
| `align_model_version_id` | TEXT | FK `model_versions.id` |
| `cost` | REAL | DTW cost |
| `registration` | TEXT | JSON similarity matrix and residual |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `alignment_anchors`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `comparison_id` | TEXT NOT NULL | FK `comparisons.id` |
| `frame_a` | INTEGER NOT NULL | Strictly increasing |
| `frame_b` | INTEGER NOT NULL | Strictly increasing |

## `renders`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `comparison_id` | TEXT | FK `comparisons.id` |
| `attempt_id` | TEXT | FK `attempts.id` |
| `layout` | TEXT NOT NULL | `side_by_side` or `overlay` |
| `options` | TEXT | JSON |
| `status` | TEXT NOT NULL | |
| `path` | TEXT | Library-relative path |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `feedback_events`

`learning/feedback.py` is the only write path for corrections.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `kind` | TEXT NOT NULL | See kinds below |
| `entity_type` | TEXT NOT NULL | |
| `entity_id` | TEXT NOT NULL | |
| `video_id` | TEXT | FK `videos.id` |
| `before` | TEXT | JSON |
| `after` | TEXT | JSON |
| `model_version_id` | TEXT | Version that produced the proposal |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

Kinds: `cut.accept`, `cut.adjust`, `cut.reject`, `cut.missed`, `cut.delete`, `outcome.correct`, `scene.edit`, `climber.reassign`, `pose.edit`, `pose.confirm`, `align.anchor`, `review.complete`.

## `model_versions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `family` | TEXT NOT NULL | `pose`, `smooth`, `event`, `align` |
| `version` | TEXT NOT NULL | |
| `path` | TEXT | Library-relative directory |
| `params` | TEXT | JSON |
| `metrics` | TEXT | JSON |
| `dataset_hash` | TEXT | |
| `n_train` | INTEGER | |
| `source` | TEXT NOT NULL | `app` or `pod` |
| `run_id` | TEXT | Pod runs only |
| `active` | INTEGER NOT NULL | One active row per family |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |

## `jobs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `kind` | TEXT NOT NULL | `ingest`, `pose`, `detect`, `cut`, `render`, `train`, `noop` |
| `lane` | TEXT NOT NULL | `media` or `compute` |
| `status` | TEXT NOT NULL | `queued`, `running`, `done`, `failed`, `cancelled` |
| `progress` | REAL | 0–1 |
| `message` | TEXT | |
| `entity_type` | TEXT | |
| `entity_id` | TEXT | |
| `error` | TEXT | |
| `created_at` | TEXT NOT NULL | ISO 8601 UTC |
| `started_at` | TEXT | |
| `finished_at` | TEXT | |

A partial unique index allows only one `queued` or `running` job per `kind` and `entity_id`.

## `settings`

User preferences and algorithm parameters live here.
Environment variables stay in the frozen `Settings` object.

| Column | Type | Notes |
| --- | --- | --- |
| `key` | TEXT PK | |
| `value` | TEXT NOT NULL | JSON |

Keys include `pose_mode`, `det_every`, `proxy_fps`, `proxy_long_side`, `pre_roll_s`, `post_roll_s`, and detector thresholds.

## `trash_items`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID |
| `kind` | TEXT NOT NULL | `video` or `attempt` |
| `entity_id` | TEXT NOT NULL | Original row id |
| `payload` | TEXT | JSON snapshot |
| `path` | TEXT | Trash folder path |
| `deleted_at` | TEXT NOT NULL | ISO 8601 UTC |

## `schema_migrations`

| Column | Type | Notes |
| --- | --- | --- |
| `version` | TEXT PK | For example `0001_init` |
| `applied_at` | TEXT NOT NULL | ISO 8601 UTC |

Running the migrations twice must change nothing.

Phase 0 applies this schema in `backend/app/migrations/0001_init.sql`.

## Files on disk, not columns

These artifacts are not SQLite columns.

| Artifact | Path |
| --- | --- |
| Pose keypoints | `pose/<video_id>/<run_id>.npz` |
| Effective track cache | `pose/<video_id>/<run_id>.effective.npz` |
| Alignment maps | `align/<comparison_id>.npz` |
| Learned model | `models/<family>/<version>/` ONNX + JSON |

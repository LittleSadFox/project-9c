-- Climbing Coach initial schema. See DATA_MODEL.md.
-- schema_migrations is created by apply_migrations() before this file runs.

CREATE TABLE boulders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    gym TEXT,
    grade TEXT,
    color TEXT,
    sector TEXT,
    set_date TEXT,
    status TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    gym TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE videos (
    id TEXT PRIMARY KEY,
    boulder_id TEXT REFERENCES boulders(id),
    session_id TEXT REFERENCES sessions(id),
    original_name TEXT NOT NULL,
    original_ext TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL,
    duration_s REAL,
    src_fps REAL,
    is_vfr INTEGER NOT NULL,
    src_width INTEGER,
    src_height INTEGER,
    rotation INTEGER,
    codec TEXT,
    recorded_at TEXT,
    proxy_fps REAL,
    proxy_width INTEGER,
    proxy_height INTEGER,
    n_frames INTEGER,
    ingest_status TEXT NOT NULL,
    pose_status TEXT NOT NULL,
    detect_status TEXT NOT NULL,
    review_status TEXT NOT NULL,
    error TEXT,
    notes TEXT,
    deleted_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE model_versions (
    id TEXT PRIMARY KEY,
    family TEXT NOT NULL,
    version TEXT NOT NULL,
    path TEXT,
    params TEXT,
    metrics TEXT,
    dataset_hash TEXT,
    n_train INTEGER,
    source TEXT NOT NULL,
    run_id TEXT,
    active INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE pose_runs (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id),
    model_version_id TEXT REFERENCES model_versions(id),
    device TEXT,
    provider TEXT,
    mode TEXT,
    det_every INTEGER,
    fps_measured REAL,
    climber_track_id INTEGER,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE pose_tracks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES pose_runs(id),
    track_id INTEGER NOT NULL,
    first_frame INTEGER NOT NULL,
    last_frame INTEGER NOT NULL,
    coverage REAL,
    vertical_travel REAL,
    is_climber INTEGER NOT NULL
);

CREATE TABLE pose_edits (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id),
    kind TEXT NOT NULL,
    frame INTEGER NOT NULL,
    kpt INTEGER,
    x REAL,
    y REAL,
    range_start INTEGER,
    range_end INTEGER,
    undone_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE scene_marks (
    video_id TEXT PRIMARY KEY REFERENCES videos(id),
    floor_line TEXT,
    top_zone TEXT,
    start_holds TEXT,
    ref_points TEXT,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE proposals (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id),
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    outcome_guess TEXT,
    confidence REAL,
    model_version_id TEXT REFERENCES model_versions(id),
    status TEXT NOT NULL,
    attempt_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE attempts (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id),
    boulder_id TEXT REFERENCES boulders(id),
    proposal_id TEXT REFERENCES proposals(id),
    start_frame INTEGER NOT NULL,
    end_frame INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    proximity INTEGER,
    exertion INTEGER,
    notes TEXT,
    rated_at TEXT,
    clip_version INTEGER NOT NULL,
    clip_status TEXT NOT NULL,
    deleted_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE events (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL REFERENCES videos(id),
    run_id TEXT,
    frame INTEGER NOT NULL,
    kind TEXT NOT NULL,
    confidence REAL,
    source TEXT NOT NULL,
    model_version_id TEXT REFERENCES model_versions(id),
    created_at TEXT NOT NULL
);

CREATE TABLE comparisons (
    id TEXT PRIMARY KEY,
    attempt_a TEXT NOT NULL REFERENCES attempts(id),
    attempt_b TEXT NOT NULL REFERENCES attempts(id),
    params TEXT,
    align_model_version_id TEXT REFERENCES model_versions(id),
    cost REAL,
    registration TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE alignment_anchors (
    id TEXT PRIMARY KEY,
    comparison_id TEXT NOT NULL REFERENCES comparisons(id),
    frame_a INTEGER NOT NULL,
    frame_b INTEGER NOT NULL
);

CREATE TABLE renders (
    id TEXT PRIMARY KEY,
    comparison_id TEXT REFERENCES comparisons(id),
    attempt_id TEXT REFERENCES attempts(id),
    layout TEXT NOT NULL,
    options TEXT,
    status TEXT NOT NULL,
    path TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE feedback_events (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    video_id TEXT REFERENCES videos(id),
    before TEXT,
    after TEXT,
    model_version_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    lane TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL,
    message TEXT,
    entity_type TEXT,
    entity_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE UNIQUE INDEX jobs_one_active
    ON jobs(kind, entity_id)
    WHERE status IN ('queued', 'running') AND entity_id IS NOT NULL;

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE trash_items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload TEXT,
    path TEXT,
    deleted_at TEXT NOT NULL
);

INSERT INTO settings(key, value) VALUES
    ('pose_mode', '"balanced"'),
    ('det_every', '5'),
    ('proxy_fps', '30'),
    ('proxy_long_side', '1280'),
    ('pre_roll_s', '1.5'),
    ('post_roll_s', '1.0');

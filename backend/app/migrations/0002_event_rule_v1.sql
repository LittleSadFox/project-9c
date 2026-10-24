-- Phase 2 slice D: seed event/rule-v1 and default detector thresholds.

INSERT INTO model_versions (
    id, family, version, path, params, metrics, dataset_hash, n_train,
    source, run_id, active, created_at
) VALUES (
    'c0ffee00-0002-4000-8000-000000000002',
    'event',
    'rule-v1',
    NULL,
    '{"leave_ground_height_s": 0.15, "leave_ground_hold_s": 0.5, "ground_return_height_s": 0.1, "ground_return_hold_s": 0.3, "drop_speed_s": 3.0, "drop_window_s": 1.0, "top_hold_s": 1.0, "top_grow_s": 0.2, "gap_fill_s": 0.5}',
    NULL,
    NULL,
    NULL,
    'app',
    NULL,
    1,
    '2026-10-24T00:00:00Z'
);

INSERT INTO settings(key, value) VALUES
    ('leave_ground_height_s', '0.15'),
    ('leave_ground_hold_s', '0.5'),
    ('ground_return_height_s', '0.1'),
    ('ground_return_hold_s', '0.3'),
    ('drop_speed_s', '3.0'),
    ('drop_window_s', '1.0'),
    ('top_hold_s', '1.0'),
    ('top_grow_s', '0.2');

"""Rule detector gates from coding_plan Phase 2."""

from __future__ import annotations

from app.core.cuts import build_proposals, proposal_inner_spans
from app.core.events import detect_events
from tests.fixtures.synth_pose import add_noise, one_attempt, standing_only, two_attempts


def _detect(video):  # type: ignore[no-untyped-def]
    return detect_events(
        video.keypoints,
        video.scores,
        video.floor_line,
        fps=video.fps,
        top_zone=video.top_zone,
    )


def test_clean_start_end_within_two_frames() -> None:
    video = one_attempt()
    events, spans = _detect(video)
    assert len(spans) == 1
    truth = video.attempts[0]
    assert abs(spans[0].leave_ground - truth.leave_ground) <= 2
    assert abs(spans[0].ground_return - truth.ground_return) <= 2
    kinds = {item.kind for item in events}
    assert "leave_ground" in kinds
    assert "ground_return" in kinds


def test_noisy_start_end_within_five_frames() -> None:
    video = add_noise(one_attempt(), sigma_s=0.02, drop_frac=0.10, seed=3)
    _events, spans = _detect(video)
    assert len(spans) == 1
    truth = video.attempts[0]
    assert abs(spans[0].leave_ground - truth.leave_ground) <= 5
    assert abs(spans[0].ground_return - truth.ground_return) <= 5


def test_standing_only_gives_zero_proposals() -> None:
    video = standing_only()
    _events, spans = _detect(video)
    proposals = build_proposals(spans, fps=video.fps, n_frames=video.n_frames)
    assert spans == []
    assert proposals == []


def test_two_attempts_give_two_proposals() -> None:
    video = two_attempts()
    _events, spans = _detect(video)
    proposals = build_proposals(spans, fps=video.fps, n_frames=video.n_frames)
    assert len(spans) == 2
    assert len(proposals) == 2
    inners = proposal_inner_spans(proposals)
    for pred, truth in zip(inners, video.attempts, strict=True):
        assert abs(pred[0] - truth.leave_ground) <= 2
        assert abs(pred[1] - truth.ground_return) <= 2


def test_sit_start_is_detected() -> None:
    video = one_attempt(sit=True, leave=40, land=130)
    _events, spans = _detect(video)
    assert len(spans) == 1
    assert abs(spans[0].leave_ground - 40) <= 2
    assert abs(spans[0].ground_return - 130) <= 2

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { getPose } from "../api/pose.js";
import { createAttempt, createdAttemptId, getVideo, videoProxyUrl, videoThumbUrl } from "../api/videos.js";
import { Hint } from "../components/Hint.jsx";
import { Notice } from "../components/Notice.jsx";
import { PlaybackPane } from "../components/PlaybackPane.jsx";
import { Timeline } from "../components/Timeline.jsx";
import { Button, Panel } from "../components/glass.jsx";
import { frameKeypoints, useKeypoints } from "../hooks/useKeypoints.js";
import { useHotkeys } from "../hooks/useHotkeys.js";
import { usePlayback } from "../hooks/usePlayback.js";
import { useUndo } from "../hooks/useUndo.js";
import { invalidate, useResource } from "../hooks/useResource.js";
import { t } from "../i18n/index.js";
import { clampFrame, inOutValid } from "../lib/frameTime.js";
import { HALPE26_EDGES } from "../lib/halpe26.js";

const OUTCOMES = ["send", "fall", "unknown"];

export function VideoReviewPage() {
  const { videoId } = useParams();
  const navigate = useNavigate();
  const videoLoader = useCallback(() => getVideo(videoId), [videoId]);
  const poseLoader = useCallback(() => getPose(videoId).catch(() => null), [videoId]);
  const video = useResource(`video:${videoId}`, videoLoader);
  const pose = useResource(`pose:${videoId}`, poseLoader);
  const data = video.data;
  const fps = (data && (data.fps || data.proxy_fps)) || 0;
  const nFrames = (data && data.n_frames) || 0;
  const ready = Boolean(nFrames && fps);
  const playback = usePlayback({ fps, nFrames });
  const undo = useUndo();
  const [inFrame, setInFrame] = useState(0);
  const [outFrame, setOutFrame] = useState(0);
  const [outcome, setOutcome] = useState("unknown");
  const [mode, setMode] = useState("overlay");
  const [zoom, setZoom] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const trailRef = useRef([]);
  const [trail, setTrail] = useState([]);

  useEffect(() => {
    setInFrame(0);
    setOutFrame(nFrames ? nFrames - 1 : 0);
  }, [nFrames, videoId]);

  const keypoints = useKeypoints(videoId, playback.frame, Boolean(pose.data));
  const current = frameKeypoints(keypoints.data, playback.frame);

  useEffect(() => {
    if (!current) {
      return;
    }
    const next = [...trailRef.current, current].slice(-12);
    trailRef.current = next;
    setTrail(next);
  }, [current, playback.frame]);

  const markIn = useCallback(
    (frame) => {
      const next = clampFrame(frame, nFrames);
      const previous = inFrame;
      undo.run({
        do: () => setInFrame(next),
        undo: () => setInFrame(previous),
      });
    },
    [inFrame, nFrames, undo],
  );

  const markOut = useCallback(
    (frame) => {
      const next = clampFrame(frame, nFrames);
      const previous = outFrame;
      undo.run({
        do: () => setOutFrame(next),
        undo: () => setOutFrame(previous),
      });
    },
    [nFrames, outFrame, undo],
  );

  const canCreate = ready && inOutValid(inFrame, outFrame, nFrames) && !busy;

  const create = useCallback(async () => {
    if (!inOutValid(inFrame, outFrame, nFrames) || busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await createAttempt(videoId, {
        start_frame: inFrame,
        end_frame: outFrame,
        outcome,
      });
      const attemptId = createdAttemptId(result);
      invalidate("attempts");
      invalidate(`video:${videoId}`);
      navigate(`/attempts/${attemptId}`);
    } catch (err) {
      setError(err.message || String(err));
      setBusy(false);
    }
  }, [busy, inFrame, nFrames, navigate, outcome, outFrame, videoId]);

  const handlers = useMemo(
    () => ({
      toggle: playback.toggle,
      pause: playback.pause,
      reverse: playback.reverse,
      forward: playback.forward,
      stepBack: () => playback.step(-1),
      stepBack10: () => playback.step(-10),
      stepForward: () => playback.step(1),
      stepForward10: () => playback.step(10),
      markIn: () => markIn(playback.frame),
      markOut: () => markOut(playback.frame),
      accept: create,
      undo: undo.undo,
      redo: undo.redo,
    }),
    [create, markIn, markOut, playback, undo.redo, undo.undo],
  );

  useHotkeys(handlers, ready);

  if (video.loading) {
    return (
      <Panel>
        <h1 className="page-title">{t("page.video.title")}</h1>
      </Panel>
    );
  }

  if (video.error || !data) {
    return (
      <Panel>
        <h1 className="page-title">{t("page.video.title")}</h1>
        <p className="page-copy">{t("page.video.empty")}</p>
      </Panel>
    );
  }

  return (
    <Panel>
      <div className="page-head">
        <h1 className="page-title">{data.original_name || t("page.video.title")}</h1>
        <Hint text={t("review.hint")} />
      </div>
      {!ready ? <Notice>{t("review.notReady")}</Notice> : null}
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <div className="review-layout">
        <div className="review-stage">
          <PlaybackPane
            src={videoProxyUrl(videoId)}
            poster={videoThumbUrl(videoId, 0)}
            playback={playback}
            fps={fps}
            nFrames={nFrames}
            mode={mode}
            onMode={setMode}
            keypoints={current}
            trail={trail}
            edges={(pose.data && pose.data.edges) || HALPE26_EDGES}
            srcWidth={data.proxy_width}
            srcHeight={data.proxy_height}
          />
          <Timeline
            nFrames={nFrames}
            fps={fps}
            frame={playback.frame}
            inFrame={inFrame}
            outFrame={outFrame}
            zoom={zoom}
            onSeek={playback.seek}
            onInChange={(value) => markIn(value)}
            onOutChange={(value) => markOut(value)}
            onZoomChange={setZoom}
          />
        </div>
        <aside className="review-inspector">
          <h2 className="panel-title">{t("review.outcome")}</h2>
          <div className="rating-outcomes">
            {OUTCOMES.map((item) => (
              <Button key={item} variant={outcome === item ? "primary" : "glass"} onClick={() => setOutcome(item)}>
                {t(`outcome.${item}`)}
              </Button>
            ))}
          </div>
          <dl className="meta-list">
            <dt>{t("timeline.in")}</dt>
            <dd className="tabular">{inFrame}</dd>
            <dt>{t("timeline.out")}</dt>
            <dd className="tabular">{outFrame}</dd>
          </dl>
          <Button variant="primary" disabled={!canCreate} onClick={create}>
            {t("action.createAttempt")}
          </Button>
        </aside>
      </div>
    </Panel>
  );
}

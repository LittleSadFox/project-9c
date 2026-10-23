import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router";

import { attemptClipUrl, getAttempt, patchAttempt } from "../api/attempts.js";
import { getPose } from "../api/pose.js";
import { getVideo, videoProxyUrl, videoThumbUrl } from "../api/videos.js";
import { Notice } from "../components/Notice.jsx";
import { PlaybackPane } from "../components/PlaybackPane.jsx";
import { RatingPanel } from "../components/RatingPanel.jsx";
import { Panel } from "../components/glass.jsx";
import { useDebouncedCallback } from "../hooks/useDebouncedCallback.js";
import { frameKeypoints, useKeypoints } from "../hooks/useKeypoints.js";
import { useHotkeys } from "../hooks/useHotkeys.js";
import { usePlayback } from "../hooks/usePlayback.js";
import { invalidate, useResource } from "../hooks/useResource.js";
import { t } from "../i18n/index.js";
import { HALPE26_EDGES } from "../lib/halpe26.js";
import { changedRatings, ratingsFrom } from "../lib/ratings.js";

export function AttemptPage() {
  const { attemptId } = useParams();
  const attemptLoader = useCallback(() => getAttempt(attemptId), [attemptId]);
  const attempt = useResource(`attempt:${attemptId}`, attemptLoader);
  const data = attempt.data;
  const videoId = data && data.video_id;
  const videoLoader = useCallback(() => (videoId ? getVideo(videoId) : Promise.resolve(null)), [videoId]);
  const poseLoader = useCallback(() => (videoId ? getPose(videoId).catch(() => null) : Promise.resolve(null)), [videoId]);
  const video = useResource(`video:${videoId || "none"}`, videoLoader);
  const pose = useResource(`pose:${videoId || "none"}`, poseLoader);

  const fps = (data && data.fps) || (video.data && (video.data.fps || video.data.proxy_fps)) || 0;
  const clipReady = Boolean(data && data.clip_status === "done" && (data.clip_url || attemptId));
  const videoStart = (data && data.start_frame) || 0;
  const videoEnd = (data && data.end_frame) || 0;
  const clipFrames = data ? Math.max(1, videoEnd - videoStart + 1) : 1;
  const sourceFrames = (video.data && video.data.n_frames) || clipFrames;
  const nFrames = clipReady ? clipFrames : sourceFrames;
  const startFrame = clipReady ? 0 : videoStart;
  const endFrame = clipReady ? clipFrames - 1 : videoEnd || Math.max(0, nFrames - 1);
  const playback = usePlayback({ fps, nFrames, startFrame, endFrame });
  const [mode, setMode] = useState("overlay");
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const trailRef = useRef([]);
  const [trail, setTrail] = useState([]);

  useEffect(() => {
    if (data) {
      setDraft(ratingsFrom(data));
    }
  }, [data]);

  const poseFrame = clipReady ? videoStart + playback.frame : playback.frame;
  const keypoints = useKeypoints(videoId, poseFrame, Boolean(pose.data));
  const current = frameKeypoints(keypoints.data, poseFrame);

  useEffect(() => {
    if (!current) {
      return;
    }
    const next = [...trailRef.current, current].slice(-12);
    trailRef.current = next;
    setTrail(next);
  }, [current, poseFrame]);

  useDebouncedCallback(
    async () => {
      if (!draft || !data) {
        return;
      }
      const patch = changedRatings(draft, data);
      if (Object.keys(patch).length === 0) {
        return;
      }
      setSaving(true);
      setSaveError(null);
      try {
        await patchAttempt(attemptId, patch);
        invalidate(`attempt:${attemptId}`);
        invalidate("attempts");
        setSaved(true);
      } catch (error) {
        setSaveError(error.message || String(error));
      } finally {
        setSaving(false);
      }
    },
    400,
    [attemptId, data, draft],
  );

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
    }),
    [playback],
  );
  useHotkeys(handlers, Boolean(data));

  if (attempt.loading) {
    return (
      <Panel>
        <h1 className="page-title">{t("page.attempt.title")}</h1>
      </Panel>
    );
  }

  if (attempt.error || !data) {
    return (
      <Panel>
        <h1 className="page-title">{t("page.attempt.title")}</h1>
        <p className="page-copy">{t("page.attempt.empty")}</p>
      </Panel>
    );
  }

  const src = clipReady ? data.clip_url || attemptClipUrl(attemptId, data.clip_version) : videoId ? videoProxyUrl(videoId) : "";

  return (
    <Panel>
      <div className="page-head">
        <h1 className="page-title">{t("page.attempt.title")}</h1>
      </div>
      {!clipReady ? <Notice tone="warn">{t("rating.clipPending")}</Notice> : null}
      <div className="review-layout">
        <div className="review-stage">
          <PlaybackPane
            src={src}
            poster={videoId ? videoThumbUrl(videoId, data.start_frame || 0) : undefined}
            playback={playback}
            fps={fps}
            nFrames={nFrames}
            mode={mode}
            onMode={setMode}
            keypoints={current}
            trail={trail}
            edges={(pose.data && pose.data.edges) || HALPE26_EDGES}
            srcWidth={video.data && video.data.proxy_width}
            srcHeight={video.data && video.data.proxy_height}
          />
        </div>
        <aside className="review-inspector">
          <RatingPanel
            value={draft}
            saving={saving}
            saved={saved}
            error={saveError}
            onChange={(next) => {
              setSaved(false);
              setDraft(next);
            }}
          />
        </aside>
      </div>
    </Panel>
  );
}

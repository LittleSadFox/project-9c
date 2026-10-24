import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router";

import { getPersons, getPose, getReviewQueue, setClimber, createPoseEdit, deletePoseEdit } from "../api/pose.js";
import { acceptProposal, batchAcceptProposals, listProposals, rejectProposal } from "../api/proposals.js";
import { copySceneFrom, getScene, putScene, sceneOrEmpty } from "../api/scene.js";
import { createAttempt, getVideo, listVideos, patchVideo, videoFrameUrl, videoProxyUrl, videoThumbUrl } from "../api/videos.js";
import { Hint } from "../components/Hint.jsx";
import { KeypointEditor } from "../components/KeypointEditor.jsx";
import { Notice } from "../components/Notice.jsx";
import { PlaybackPane } from "../components/PlaybackPane.jsx";
import { ProposalList } from "../components/ProposalList.jsx";
import { ReviewQueue } from "../components/ReviewQueue.jsx";
import { SceneMarksEditor } from "../components/SceneMarksEditor.jsx";
import { Timeline } from "../components/Timeline.jsx";
import { Button, Panel, Sheet } from "../components/glass.jsx";
import { frameKeypoints, useKeypoints } from "../hooks/useKeypoints.js";
import { useHotkeys } from "../hooks/useHotkeys.js";
import { usePlayback } from "../hooks/usePlayback.js";
import { useUndo } from "../hooks/useUndo.js";
import { invalidate, useResource } from "../hooks/useResource.js";
import { t } from "../i18n/index.js";
import { clampFrame, inOutValid } from "../lib/frameTime.js";
import { HALPE26_EDGES } from "../lib/halpe26.js";
import { asList, emptyScene, pendingProposals } from "../lib/lists.js";
import { acceptPayload, canFinishReview, nextPending } from "../lib/review.js";

const OUTCOMES = ["send", "fall", "unknown"];
const REASONS = ["not_attempt", "duplicate", "other"];

function emptyOnMissing(error) {
  if (error && (error.status === 404 || error.status === 501)) {
    return [];
  }
  throw error;
}

export function VideoReviewPage() {
  const { videoId } = useParams();
  const videoLoader = useCallback(() => getVideo(videoId), [videoId]);
  const poseLoader = useCallback(() => getPose(videoId).catch(() => null), [videoId]);
  const sceneLoader = useCallback(() => getScene(videoId).catch(sceneOrEmpty), [videoId]);
  const proposalLoader = useCallback(() => listProposals(videoId).catch(emptyOnMissing), [videoId]);
  const queueLoader = useCallback(() => getReviewQueue(videoId).catch(emptyOnMissing), [videoId]);
  const video = useResource(`video:${videoId}`, videoLoader);
  const pose = useResource(`pose:${videoId}`, poseLoader);
  const sceneRes = useResource(`scene:${videoId}`, sceneLoader);
  const proposalsRes = useResource(`proposals:${videoId}`, proposalLoader);
  const queueRes = useResource(`queue:${videoId}`, queueLoader);
  const data = video.data;
  const fps = (data && (data.fps || data.proxy_fps)) || 0;
  const nFrames = (data && data.n_frames) || 0;
  const srcWidth = (data && data.proxy_width) || 0;
  const srcHeight = (data && data.proxy_height) || 0;
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
  const [selectedId, setSelectedId] = useState(null);
  const [checkedIds, setCheckedIds] = useState([]);
  const [reason, setReason] = useState("not_attempt");
  const [sheet, setSheet] = useState(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [sceneDraft, setSceneDraft] = useState(null);
  const [swapRange, setSwapRange] = useState([0, 0]);
  const [draftPoints, setDraftPoints] = useState(null);
  const trailRef = useRef([]);
  const [trail, setTrail] = useState([]);

  const boulderId = data && data.boulder_id;
  const boulderLoader = useCallback(
    () => (boulderId ? listVideos({ boulder_id: boulderId, limit: 50 }) : Promise.resolve({ items: [] })),
    [boulderId],
  );
  const boulderVideos = useResource(`videos:boulder:${boulderId || "none"}`, boulderLoader);

  const personsLoader = useCallback(() => {
    if (!editorOpen) {
      return Promise.resolve([]);
    }
    return getPersons(videoId, playback.frame).catch(emptyOnMissing);
  }, [editorOpen, playback.frame, videoId]);
  const persons = useResource(
    `persons:${videoId}:${playback.frame}:${editorOpen ? 1 : 0}`,
    personsLoader,
  );

  const proposals = asList(proposalsRes.data);
  const pending = pendingProposals(proposals);
  const selected = proposals.find((item) => item.id === selectedId) || pending[0] || null;
  const scene = sceneDraft || sceneRes.data || emptyScene();
  const canFinish =
    Boolean(data) && !proposalsRes.loading && canFinishReview(proposals, data.review_status);
  const proposalsRef = useRef(proposals);
  const seekRef = useRef(playback.seek);
  proposalsRef.current = proposals;
  seekRef.current = playback.seek;

  useEffect(() => {
    if (sceneRes.data && !sceneDraft) {
      setSceneDraft(sceneRes.data);
    }
  }, [sceneDraft, sceneRes.data]);

  useEffect(() => {
    setInFrame(0);
    setOutFrame(nFrames ? nFrames - 1 : 0);
    setSelectedId(null);
    setCheckedIds([]);
    setSceneDraft(null);
    setEditorOpen(false);
    setError(null);
  }, [nFrames, videoId]);

  useEffect(() => {
    if (!selectedId && pending[0]) {
      setSelectedId(pending[0].id);
    }
  }, [pending, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      return;
    }
    const item = proposalsRef.current.find((proposal) => proposal.id === selectedId);
    if (!item) {
      return;
    }
    setInFrame(item.start_frame);
    setOutFrame(item.end_frame);
    setOutcome(item.outcome_guess || "unknown");
    seekRef.current(item.start_frame);
  }, [selectedId]);

  const keypoints = useKeypoints(videoId, playback.frame, Boolean(pose.data));
  const current = draftPoints || frameKeypoints(keypoints.data, playback.frame);

  useEffect(() => {
    setDraftPoints(null);
  }, [playback.frame]);

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

  const refreshReview = useCallback(() => {
    invalidate(`proposals:${videoId}`);
    invalidate(`video:${videoId}`);
    invalidate("attempts");
  }, [videoId]);

  const runBusy = useCallback(
    async (work) => {
      if (busy) {
        return;
      }
      setBusy(true);
      setError(null);
      try {
        await work();
      } catch (err) {
        setError(err.message || String(err));
      } finally {
        setBusy(false);
      }
    },
    [busy],
  );

  const acceptSelected = useCallback(async () => {
    if (!selected || selected.status !== "pending" || busy) {
      return;
    }
    await runBusy(async () => {
      await acceptProposal(selected.id, acceptPayload(selected, inFrame, outFrame, outcome));
      const next = nextPending(
        proposals.map((item) => (item.id === selected.id ? { ...item, status: "accepted" } : item)),
        selected.id,
      );
      setSelectedId(next && next.id);
      setCheckedIds((ids) => ids.filter((id) => id !== selected.id));
      refreshReview();
    });
  }, [busy, inFrame, outcome, outFrame, proposals, refreshReview, runBusy, selected]);

  const rejectSelected = useCallback(async () => {
    if (!selected || selected.status !== "pending" || busy) {
      return;
    }
    await runBusy(async () => {
      await rejectProposal(selected.id, reason);
      const next = nextPending(
        proposals.map((item) => (item.id === selected.id ? { ...item, status: "rejected" } : item)),
        selected.id,
      );
      setSelectedId(next && next.id);
      setCheckedIds((ids) => ids.filter((id) => id !== selected.id));
      setSheet(null);
      refreshReview();
    });
  }, [busy, proposals, reason, refreshReview, runBusy, selected]);

  const batchAccept = useCallback(async () => {
    const ids = (checkedIds.length ? checkedIds : pending.map((item) => item.id)).filter(Boolean);
    if (!ids.length) {
      return;
    }
    await runBusy(async () => {
      await batchAcceptProposals(ids);
      setCheckedIds([]);
      setSelectedId(null);
      refreshReview();
    });
  }, [checkedIds, pending, refreshReview, runBusy]);

  const addMissed = useCallback(async () => {
    if (!inOutValid(inFrame, outFrame, nFrames) || busy) {
      return;
    }
    await runBusy(async () => {
      await createAttempt(videoId, { start_frame: inFrame, end_frame: outFrame, outcome });
      refreshReview();
    });
  }, [busy, inFrame, nFrames, outcome, outFrame, refreshReview, runBusy, videoId]);

  const finishReview = useCallback(async () => {
    if (!canFinish || busy) {
      if (!canFinish && pending.length) {
        setError(t("review.pendingBlock"));
      }
      return;
    }
    await runBusy(async () => {
      await patchVideo(videoId, { review_status: "reviewed" });
      invalidate(`video:${videoId}`);
    });
  }, [busy, canFinish, pending.length, runBusy, videoId]);

  const saveScene = useCallback(
    async (next) => {
      const previous = sceneRes.data || emptyScene();
      await undo.run({
        do: async () => {
          await putScene(videoId, next);
          setSceneDraft({ ...next, source: "user" });
          invalidate(`scene:${videoId}`);
        },
        undo: async () => {
          await putScene(videoId, previous);
          setSceneDraft(previous);
          invalidate(`scene:${videoId}`);
        },
      });
    },
    [sceneRes.data, undo, videoId],
  );

  const copyScene = useCallback(
    async (otherId) => {
      await runBusy(async () => {
        const result = await copySceneFrom(videoId, otherId);
        setSceneDraft((result && result.scene) || result);
        invalidate(`scene:${videoId}`);
      });
    },
    [runBusy, videoId],
  );

  const postEdit = useCallback(
    async (body) => {
      let created = null;
      await undo.run({
        do: async () => {
          created = await createPoseEdit(videoId, body);
          invalidate(`keypoints:${videoId}`);
          invalidate(`queue:${videoId}`);
        },
        undo: async () => {
          if (created && created.edit_id) {
            await deletePoseEdit(videoId, created.edit_id);
            invalidate(`keypoints:${videoId}`);
            invalidate(`queue:${videoId}`);
          }
        },
      });
    },
    [undo, videoId],
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
      markIn: () => markIn(playback.frame),
      markOut: () => markOut(playback.frame),
      accept: acceptSelected,
      reject: rejectSelected,
      editSkeleton: () => setEditorOpen((value) => !value),
      undo: undo.undo,
      redo: undo.redo,
    }),
    [acceptSelected, markIn, markOut, playback, rejectSelected, undo.redo, undo.undo],
  );

  useHotkeys(handlers, ready && !sheet);

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

  const reviewed = data.review_status === "reviewed";

  return (
    <Panel>
      <div className="page-head">
        <h1 className="page-title">{data.original_name || t("page.video.title")}</h1>
        <a className="media-card-link" href="/library">
          {t("nav.library")}
        </a>
        <Hint text={t("review.hint")} />
      </div>
      {!ready ? <Notice>{t("review.notReady")}</Notice> : null}
      {data.detect_status && data.detect_status !== "done" ? <Notice>{t("review.detectWait")}</Notice> : null}
      {reviewed ? <Notice>{t("review.reviewed")}</Notice> : null}
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <div className="review-layout">
        <div className="review-stage">
          {editorOpen ? (
            <KeypointEditor
              src={videoFrameUrl(videoId, playback.frame)}
              srcWidth={srcWidth}
              srcHeight={srcHeight}
              frame={playback.frame}
              keypoints={current || []}
              persons={asList(persons.data)}
              swapStart={swapRange[0]}
              swapEnd={swapRange[1]}
              onSwapRangeChange={setSwapRange}
              onMove={(index, x, y) => {
                setDraftPoints((prev) => {
                  const base = prev || (current ? current.map((point) => (point ? [...point] : point)) : []);
                  const next = base.map((point) => (point ? [...point] : point));
                  if (next[index]) {
                    next[index][0] = x;
                    next[index][1] = y;
                  }
                  return next;
                });
              }}
              onMoveEnd={(index) => {
                const point = (draftPoints || current || [])[index];
                if (!point) {
                  return;
                }
                postEdit({
                  kind: "move",
                  frame: playback.frame,
                  points: [{ kpt: index, x: point[0], y: point[1] }],
                });
              }}
              onSwap={() =>
                postEdit({ kind: "lr_swap", frame: playback.frame, range: [swapRange[0], swapRange[1]] })
              }
              onInvalid={() => postEdit({ kind: "invalid", frame: playback.frame })}
              onConfirm={() => postEdit({ kind: "confirm", frame: playback.frame })}
              onSelectPerson={(person) =>
                undo.run({
                  do: () => setClimber(videoId, { track_id: person.track_id }),
                  undo: () => setClimber(videoId, { track_id: pose.data && pose.data.climber_track_id }),
                })
              }
            />
          ) : (
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
              srcWidth={srcWidth}
              srcHeight={srcHeight}
            />
          )}
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
          <div className="inspector-actions review-primary">
            <Button variant="primary" disabled={!canFinish || busy || reviewed} onClick={finishReview}>
              {t("action.finishReview")}
            </Button>
          </div>
          <h2 className="panel-title">{t("proposals.title")}</h2>
          <ProposalList
            proposals={proposals}
            selectedId={selected && selected.id}
            checkedIds={checkedIds}
            onSelect={(item) => {
              setSelectedId(item.id);
              playback.seek(item.start_frame);
            }}
            onToggle={(id) =>
              setCheckedIds((ids) => (ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]))
            }
          />
          <h2 className="panel-title">{t("review.outcome")}</h2>
          <div className="rating-outcomes">
            {OUTCOMES.map((item) => (
              <button
                key={item}
                type="button"
                className={`transport-mode${outcome === item ? " transport-mode-on" : ""}`}
                aria-pressed={outcome === item}
                onClick={() => setOutcome(item)}
              >
                {t(`outcome.${item}`)}
              </button>
            ))}
          </div>
          <label className="rating-field">
            {t("review.reason")}
            <select
              className="search-input"
              aria-label={t("review.reason")}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            >
              {REASONS.map((item) => (
                <option key={item} value={item}>
                  {t(`reason.${item}`)}
                </option>
              ))}
            </select>
          </label>
          <dl className="meta-list">
            <dt>{t("timeline.in")}</dt>
            <dd className="tabular">{inFrame}</dd>
            <dt>{t("timeline.out")}</dt>
            <dd className="tabular">{outFrame}</dd>
          </dl>
          <div className="inspector-actions">
            <Button variant="glass" disabled={!selected || selected.status !== "pending" || busy} onClick={acceptSelected}>
              {t("action.accept")}
            </Button>
            <Button variant="glass" disabled={!selected || selected.status !== "pending" || busy} onClick={() => setSheet("reject")}>
              {t("action.reject")}
            </Button>
            <Button variant="glass" disabled={!pending.length || busy} onClick={batchAccept}>
              {t("action.batchAccept")}
            </Button>
            <Button variant="glass" disabled={!inOutValid(inFrame, outFrame, nFrames) || busy} onClick={addMissed}>
              {t("action.addMissed")}
            </Button>
            <Button variant="glass" onClick={() => setEditorOpen((value) => !value)}>
              {t("action.editSkeleton")}
            </Button>
          </div>
          <SceneMarksEditor
            scene={scene}
            srcWidth={srcWidth}
            srcHeight={srcHeight}
            frameSrc={videoFrameUrl(videoId, playback.frame)}
            videos={asList(boulderVideos.data)}
            currentVideoId={videoId}
            onChange={setSceneDraft}
            onSave={saveScene}
            onCopy={copyScene}
            busy={busy}
          />
          <ReviewQueue
            items={asList(queueRes.data)}
            currentFrame={playback.frame}
            onJump={(item) => {
              playback.seek(item.frame);
              setEditorOpen(true);
              setSwapRange([item.frame, item.frame]);
            }}
          />
        </aside>
      </div>
      <Sheet open={sheet === "reject"} title={t("review.rejectTitle")} onClose={() => setSheet(null)}>
        <h2 className="panel-title">{t("review.rejectTitle")}</h2>
        <p className="page-copy">{t("review.rejectBody")}</p>
        <div className="inspector-actions">
          <Button variant="danger" onClick={rejectSelected}>
            {t("action.confirmReject")}
          </Button>
          <Button variant="glass" onClick={() => setSheet(null)}>
            {t("action.cancel")}
          </Button>
        </div>
      </Sheet>
    </Panel>
  );
}

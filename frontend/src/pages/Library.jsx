import { useCallback, useEffect, useMemo, useReducer } from "react";
import { useNavigate, useParams } from "react-router";

import { listAttempts } from "../api/attempts.js";
import { createBoulder, listBoulders } from "../api/boulders.js";
import { ApiError } from "../api/client.js";
import { listSessions } from "../api/sessions.js";
import { emptyTrash, listTrash, restoreTrash } from "../api/trash.js";
import { deleteVideo, listVideos, reprocessVideo, uploadVideo } from "../api/videos.js";
import { AttemptCard } from "../components/AttemptCard.jsx";
import { DropZone } from "../components/DropZone.jsx";
import { Hint } from "../components/Hint.jsx";
import { Notice } from "../components/Notice.jsx";
import { SplitView } from "../components/SplitView.jsx";
import { VideoCard } from "../components/VideoCard.jsx";
import { VideoGrid } from "../components/VideoGrid.jsx";
import { Button, Panel, Sheet } from "../components/glass.jsx";
import { useDebouncedCallback } from "../hooks/useDebouncedCallback.js";
import { invalidate, useResource } from "../hooks/useResource.js";
import { t } from "../i18n/index.js";
import { formatBytes, formatTimecode } from "../lib/format.js";

const initial = {
  draftQuery: "",
  query: "",
  filter: { kind: "all" },
  selectedVideoId: null,
  selectedAttemptId: null,
  uploads: [],
  sheet: null,
  boulderForm: { name: "", gym: "", grade: "" },
  notice: null,
};

function reducer(state, action) {
  switch (action.type) {
    case "draftQuery":
      return { ...state, draftQuery: action.value };
    case "commitQuery":
      return { ...state, query: state.draftQuery };
    case "filter":
      return {
        ...state,
        filter: action.filter,
        selectedVideoId: null,
        selectedAttemptId: null,
      };
    case "selectVideo":
      return { ...state, selectedVideoId: action.id, selectedAttemptId: null };
    case "selectAttempt":
      return { ...state, selectedAttemptId: action.id, selectedVideoId: null };
    case "uploads":
      return { ...state, uploads: action.uploads };
    case "sheet":
      return { ...state, sheet: action.sheet };
    case "boulderForm":
      return { ...state, boulderForm: { ...state.boulderForm, ...action.value } };
    case "notice":
      return { ...state, notice: action.notice };
    default:
      return state;
  }
}

function itemsOf(resource) {
  if (!resource || !resource.data) {
    return [];
  }
  return resource.data.items || [];
}

export function LibraryPage() {
  const { boulderId } = useParams();
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(reducer, initial);

  useEffect(() => {
    if (boulderId) {
      dispatch({ type: "filter", filter: { kind: "boulder", id: boulderId } });
    }
  }, [boulderId]);

  useDebouncedCallback(
    () => {
      dispatch({ type: "commitQuery" });
    },
    250,
    [state.draftQuery],
  );

  const boulderLoader = useCallback(() => listBoulders({ limit: 100, offset: 0, q: state.query }), [state.query]);
  const sessionLoader = useCallback(() => listSessions({ limit: 100, offset: 0 }), []);
  const boulders = useResource(`boulders:${state.query}`, boulderLoader);
  const sessions = useResource("sessions", sessionLoader);

  const videoParams = useMemo(() => {
    const params = { limit: 100, offset: 0, sort: "-recorded_at", q: state.query };
    if (state.filter.kind === "review") {
      params.review_status = "unreviewed";
    }
    if (state.filter.kind === "boulder") {
      params.boulder_id = state.filter.id;
    }
    if (state.filter.kind === "session") {
      params.session_id = state.filter.id;
    }
    return params;
  }, [state.filter, state.query]);

  const videoKey = `videos:${JSON.stringify(videoParams)}`;
  const videoLoader = useCallback(() => listVideos(videoParams), [videoParams]);
  const videos = useResource(videoKey, videoLoader);

  const attemptParams = useMemo(() => {
    if (state.filter.kind !== "boulder") {
      return null;
    }
    return { boulder_id: state.filter.id, limit: 100, offset: 0 };
  }, [state.filter]);
  const attemptLoader = useCallback(() => {
    if (!attemptParams) {
      return Promise.resolve({ items: [], total: 0 });
    }
    return listAttempts(attemptParams);
  }, [attemptParams]);
  const attempts = useResource(`attempts:${attemptParams ? attemptParams.boulder_id : "none"}`, attemptLoader);

  const trashLoader = useCallback(() => listTrash(), []);
  const trash = useResource("trash", trashLoader);

  const boulderItems = itemsOf(boulders);
  const sessionItems = itemsOf(sessions);
  const gyms = [...new Set(boulderItems.map((item) => item.gym).filter(Boolean))];

  const videoItems = useMemo(() => {
    let list = itemsOf(videos);
    if (state.filter.kind === "unsorted") {
      list = list.filter((item) => !item.boulder_id);
    }
    if (state.filter.kind === "gym") {
      const ids = new Set(boulderItems.filter((item) => item.gym === state.filter.id).map((item) => item.id));
      list = list.filter((item) => ids.has(item.boulder_id));
    }
    return list;
  }, [boulderItems, state.filter, videos]);

  const attemptItems = itemsOf(attempts);
  const trashItems = itemsOf(trash);
  const selectedVideo = videoItems.find((item) => item.id === state.selectedVideoId) || null;
  const selectedAttempt = attemptItems.find((item) => item.id === state.selectedAttemptId) || null;
  const selectedBoulderId = state.filter.kind === "boulder" ? state.filter.id : selectedVideo && selectedVideo.boulder_id;

  async function handleFiles(files) {
    const next = [...state.uploads];
    for (const file of files) {
      const id = `${file.name}-${file.size}-${file.lastModified}-${Date.now()}`;
      const row = { id, name: file.name, progress: 0, error: null, duplicateId: null };
      next.push(row);
      dispatch({ type: "uploads", uploads: [...next] });
      try {
        const result = await uploadVideo(
          file,
          { boulder_id: selectedBoulderId },
          (progress) => {
            row.progress = progress;
            dispatch({ type: "uploads", uploads: [...next] });
          },
        );
        row.progress = 1;
        row.video = result && result.video;
        dispatch({ type: "uploads", uploads: [...next] });
        invalidate("videos");
        invalidate("boulders");
      } catch (error) {
        row.error = error instanceof ApiError ? error.message : String(error);
        row.duplicateId = error instanceof ApiError ? error.details.existing_video_id : null;
        dispatch({ type: "uploads", uploads: [...next] });
      }
    }
  }

  async function handleCreateBoulder() {
    if (!state.boulderForm.name.trim()) {
      return;
    }
    await createBoulder({
      name: state.boulderForm.name.trim(),
      gym: state.boulderForm.gym || undefined,
      grade: state.boulderForm.grade || undefined,
    });
    invalidate("boulders");
    dispatch({ type: "sheet", sheet: null });
    dispatch({ type: "boulderForm", value: { name: "", gym: "", grade: "" } });
  }

  async function handleDeleteVideo() {
    if (!selectedVideo) {
      return;
    }
    await deleteVideo(selectedVideo.id);
    invalidate("videos");
    invalidate("attempts");
    invalidate("trash");
    dispatch({ type: "selectVideo", id: null });
    dispatch({ type: "sheet", sheet: null });
  }

  function setFilter(filter) {
    dispatch({ type: "filter", filter });
    if (filter.kind === "boulder") {
      navigate(`/library/boulders/${filter.id}`);
    } else {
      navigate("/library");
    }
  }

  const sidebar = (
    <nav className="library-nav" aria-label={t("library.sidebar")}>
      <button type="button" className={state.filter.kind === "all" ? "is-on" : ""} onClick={() => setFilter({ kind: "all" })}>
        {t("library.all")}
      </button>
      <button
        type="button"
        className={state.filter.kind === "unsorted" ? "is-on" : ""}
        onClick={() => setFilter({ kind: "unsorted" })}
      >
        {t("library.unsorted")}
      </button>
      <button
        type="button"
        className={state.filter.kind === "review" ? "is-on" : ""}
        onClick={() => setFilter({ kind: "review" })}
      >
        {t("library.review")}
      </button>
      <h2 className="sidebar-heading">{t("library.gyms")}</h2>
      {gyms.map((gym) => (
        <button
          key={gym}
          type="button"
          className={state.filter.kind === "gym" && state.filter.id === gym ? "is-on" : ""}
          onClick={() => setFilter({ kind: "gym", id: gym })}
        >
          {gym}
        </button>
      ))}
      <h2 className="sidebar-heading">{t("library.boulders")}</h2>
      {boulderItems.length === 0 ? <div className="sidebar-empty">{t("library.noBoulders")}</div> : null}
      {boulderItems.map((item) => (
        <button
          key={item.id}
          type="button"
          className={state.filter.kind === "boulder" && state.filter.id === item.id ? "is-on" : ""}
          onClick={() => setFilter({ kind: "boulder", id: item.id })}
        >
          {item.name}
        </button>
      ))}
      <Button variant="glass" onClick={() => dispatch({ type: "sheet", sheet: "boulder" })}>
        {t("action.newBoulder")}
      </Button>
      <h2 className="sidebar-heading">{t("library.sessions")}</h2>
      {sessionItems.length === 0 ? <div className="sidebar-empty">{t("library.noSessions")}</div> : null}
      {sessionItems.map((item) => (
        <button
          key={item.id}
          type="button"
          className={state.filter.kind === "session" && state.filter.id === item.id ? "is-on" : ""}
          onClick={() => setFilter({ kind: "session", id: item.id })}
        >
          {item.date}
        </button>
      ))}
      <button
        type="button"
        className={state.filter.kind === "trash" ? "is-on" : ""}
        onClick={() => setFilter({ kind: "trash" })}
      >
        {t("library.trash")}
      </button>
    </nav>
  );

  const inspector = (
    <div className="inspector">
      <h2 className="panel-title">{t("library.inspector")}</h2>
      {selectedVideo ? (
        <dl className="meta-list">
          <dt>{t("page.video.title")}</dt>
          <dd>{selectedVideo.original_name}</dd>
          <dt>{t("meta.duration")}</dt>
          <dd className="tabular">{formatTimecode(selectedVideo.n_frames || 0, selectedVideo.fps || selectedVideo.proxy_fps)}</dd>
          <dt>{t("meta.size")}</dt>
          <dd className="tabular">{formatBytes(selectedVideo.size_bytes)}</dd>
          <dt>{t("meta.ingest")}</dt>
          <dd>{t(`status.${selectedVideo.ingest_status || "pending"}`)}</dd>
          <dt>{t("meta.pose")}</dt>
          <dd>{t(`status.${selectedVideo.pose_status || "pending"}`)}</dd>
          <dt>{t("meta.review")}</dt>
          <dd>{t(`status.${selectedVideo.review_status || "unreviewed"}`)}</dd>
          <div className="inspector-actions">
            <Button variant="primary" onClick={() => navigate(`/videos/${selectedVideo.id}`)}>
              {t("action.openVideo")}
            </Button>
            <Button variant="glass" onClick={() => reprocessVideo(selectedVideo.id, "pose")}>
              {t("action.reprocess")}
            </Button>
            <Button variant="danger" onClick={() => dispatch({ type: "sheet", sheet: "deleteVideo" })}>
              {t("action.delete")}
            </Button>
          </div>
        </dl>
      ) : selectedAttempt ? (
        <dl className="meta-list">
          <dt>{t("page.attempt.title")}</dt>
          <dd>{t(`outcome.${selectedAttempt.outcome || "unknown"}`)}</dd>
          <dt>{t("rating.proximity")}</dt>
          <dd className="tabular">{selectedAttempt.proximity ?? "—"}</dd>
          <dt>{t("rating.exertion")}</dt>
          <dd className="tabular">{selectedAttempt.exertion ?? "—"}</dd>
          <Button variant="primary" onClick={() => navigate(`/attempts/${selectedAttempt.id}`)}>
            {t("action.openAttempt")}
          </Button>
        </dl>
      ) : (
        <p className="page-copy">{t("library.selectedNone")}</p>
      )}
    </div>
  );

  return (
    <Panel>
      <div className="page-head">
        <h1 className="page-title">{t("page.library.title")}</h1>
        <Hint text={t("hint.library")} />
        <label className="search-field">
          <span className="sr-only">{t("library.search")}</span>
          <input
            className="search-input"
            value={state.draftQuery}
            placeholder={t("library.search")}
            onChange={(event) => dispatch({ type: "draftQuery", value: event.target.value })}
          />
        </label>
      </div>
      {state.notice ? <Notice>{state.notice}</Notice> : null}
      {videos.error ? <Notice tone="danger">{videos.error.message}</Notice> : null}
      <SplitView sidebar={sidebar} inspector={inspector}>
        {state.filter.kind === "trash" ? (
          <div>
            <div className="section-head">
              <h2 className="panel-title">{t("library.trash")}</h2>
              <Button variant="danger" disabled={trashItems.length === 0} onClick={() => dispatch({ type: "sheet", sheet: "emptyTrash" })}>
                {t("action.emptyTrash")}
              </Button>
            </div>
            {trashItems.length === 0 ? <p className="page-copy">{t("library.noTrash")}</p> : null}
            <ul className="trash-list">
              {trashItems.map((item) => (
                <li key={item.id} className="trash-row">
                  <span>
                    {item.kind} · {item.entity_id}
                  </span>
                  <Button
                    variant="glass"
                    onClick={async () => {
                      await restoreTrash(item.id);
                      invalidate("trash");
                      invalidate("videos");
                      invalidate("attempts");
                    }}
                  >
                    {t("action.restore")}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <DropZone onFiles={handleFiles}>
            {state.uploads.length > 0 ? (
              <ul className="upload-list">
                {state.uploads.map((item) => (
                  <li key={item.id} className="upload-row">
                    <span>{item.name}</span>
                    <span className="tabular">
                      {item.error
                        ? item.duplicateId
                          ? t("library.duplicate")
                          : item.error
                        : `${Math.round((item.progress || 0) * 100)}%`}
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
            <h2 className="panel-title">{t("library.videos")}</h2>
            <VideoGrid empty={t("page.library.empty")}>
              {videoItems.map((video) => (
                <VideoCard
                  key={video.id}
                  video={video}
                  selected={video.id === state.selectedVideoId}
                  onSelect={(item) => dispatch({ type: "selectVideo", id: item.id })}
                />
              ))}
            </VideoGrid>
            {state.filter.kind === "boulder" ? (
              <>
                <h2 className="panel-title">{t("library.attempts")}</h2>
                <VideoGrid empty={t("library.noAttempts")}>
                  {attemptItems.map((attempt) => (
                    <AttemptCard
                      key={attempt.id}
                      attempt={attempt}
                      selected={attempt.id === state.selectedAttemptId}
                      onSelect={(item) => dispatch({ type: "selectAttempt", id: item.id })}
                    />
                  ))}
                </VideoGrid>
              </>
            ) : null}
          </DropZone>
        )}
      </SplitView>
      <Sheet open={state.sheet === "boulder"} title={t("boulder.newTitle")} onClose={() => dispatch({ type: "sheet", sheet: null })}>
        <h2 className="panel-title">{t("boulder.newTitle")}</h2>
        <label className="rating-field">
          {t("boulder.name")}
          <input
            className="search-input"
            aria-label={t("boulder.name")}
            value={state.boulderForm.name}
            onChange={(event) => dispatch({ type: "boulderForm", value: { name: event.target.value } })}
          />
        </label>
        <label className="rating-field">
          {t("boulder.gym")}
          <input
            className="search-input"
            aria-label={t("boulder.gym")}
            value={state.boulderForm.gym}
            onChange={(event) => dispatch({ type: "boulderForm", value: { gym: event.target.value } })}
          />
        </label>
        <label className="rating-field">
          {t("boulder.grade")}
          <input
            className="search-input"
            aria-label={t("boulder.grade")}
            value={state.boulderForm.grade}
            onChange={(event) => dispatch({ type: "boulderForm", value: { grade: event.target.value } })}
          />
        </label>
        <div className="inspector-actions">
          <Button variant="primary" disabled={!state.boulderForm.name.trim()} onClick={handleCreateBoulder}>
            {t("action.saveBoulder")}
          </Button>
          <Button variant="glass" onClick={() => dispatch({ type: "sheet", sheet: null })}>
            {t("action.cancel")}
          </Button>
        </div>
      </Sheet>
      <Sheet open={state.sheet === "deleteVideo"} title={t("delete.videoTitle")} onClose={() => dispatch({ type: "sheet", sheet: null })}>
        <h2 className="panel-title">{t("delete.videoTitle")}</h2>
        <p className="page-copy">{t("delete.videoBody")}</p>
        <div className="inspector-actions">
          <Button variant="danger" onClick={handleDeleteVideo}>
            {t("action.confirmDelete")}
          </Button>
          <Button variant="glass" onClick={() => dispatch({ type: "sheet", sheet: null })}>
            {t("action.cancel")}
          </Button>
        </div>
      </Sheet>
      <Sheet open={state.sheet === "emptyTrash"} title={t("delete.trashTitle")} onClose={() => dispatch({ type: "sheet", sheet: null })}>
        <h2 className="panel-title">{t("delete.trashTitle")}</h2>
        <p className="page-copy">{t("delete.trashBody")}</p>
        <div className="inspector-actions">
          <Button
            variant="danger"
            onClick={async () => {
              await emptyTrash();
              invalidate("trash");
              dispatch({ type: "sheet", sheet: null });
            }}
          >
            {t("action.emptyTrash")}
          </Button>
          <Button variant="glass" onClick={() => dispatch({ type: "sheet", sheet: null })}>
            {t("action.cancel")}
          </Button>
        </div>
      </Sheet>
    </Panel>
  );
}

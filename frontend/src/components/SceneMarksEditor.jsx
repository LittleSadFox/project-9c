import { useEffect, useRef, useState } from "react";

import { t } from "../i18n/index.js";
import { clampPoint, clientToSource } from "../lib/geometry.js";
import { emptyScene } from "../lib/lists.js";
import { Button } from "./glass.jsx";

const TOOLS = ["floor", "zone", "holds", "refs"];

function nextRefName(points) {
  return `P${(points || []).length + 1}`;
}

export function applySceneClick(scene, tool, point, name) {
  const next = {
    ...emptyScene(),
    ...scene,
    floor_line: [...(scene.floor_line || [])],
    top_zone: [...(scene.top_zone || [])],
    start_holds: [...(scene.start_holds || [])],
    ref_points: [...(scene.ref_points || [])],
    source: "user",
  };
  if (tool === "floor") {
    if (next.floor_line.length >= 2) {
      next.floor_line = [point];
    } else {
      next.floor_line = [...next.floor_line, point];
    }
  } else if (tool === "zone") {
    next.top_zone = [...next.top_zone, point];
  } else if (tool === "holds") {
    next.start_holds = [...next.start_holds, point];
  } else if (tool === "refs") {
    next.ref_points = [...next.ref_points, { name: name || nextRefName(next.ref_points), x: point[0], y: point[1] }];
  }
  return next;
}

export function SceneMarksEditor({
  scene,
  srcWidth = 0,
  srcHeight = 0,
  frameSrc,
  videos = [],
  currentVideoId,
  onChange,
  onSave,
  onCopy,
  busy = false,
}) {
  const [tool, setTool] = useState("floor");
  const [copyId, setCopyId] = useState("");
  const [refName, setRefName] = useState("");
  const stageRef = useRef(null);
  const draft = scene || emptyScene();

  useEffect(() => {
    setCopyId("");
  }, [currentVideoId]);

  function onStageClick(event) {
    const rect = stageRef.current && stageRef.current.getBoundingClientRect();
    const raw = clientToSource(event.clientX, event.clientY, rect, srcWidth, srcHeight);
    const point = clampPoint(raw[0], raw[1], srcWidth, srcHeight);
    onChange(applySceneClick(draft, tool, point, refName.trim()));
  }

  const others = videos.filter((item) => item.id !== currentVideoId);

  return (
    <section className="scene-editor" aria-label={t("scene.title")}>
      <h2 className="panel-title">{t("scene.title")}</h2>
      <div className="scene-tools" role="group" aria-label={t("scene.tools")}>
        {TOOLS.map((id) => (
          <button
            key={id}
            type="button"
            className={`transport-mode${tool === id ? " transport-mode-on" : ""}`}
            aria-pressed={tool === id}
            onClick={() => setTool(id)}
          >
            {t(`scene.${id}`)}
          </button>
        ))}
      </div>
      {tool === "refs" ? (
        <label className="rating-field">
          {t("scene.refName")}
          <input
            className="search-input"
            aria-label={t("scene.refName")}
            value={refName}
            onChange={(event) => setRefName(event.target.value)}
          />
        </label>
      ) : null}
      <div
        ref={stageRef}
        className="scene-stage"
        role="application"
        aria-label={t("scene.stage")}
        onClick={onStageClick}
      >
        {frameSrc ? <img className="scene-frame" src={frameSrc} alt="" /> : null}
        <p className="scene-meta tabular">
          {t("scene.floor")}: {draft.floor_line.length} · {t("scene.zone")}: {draft.top_zone.length} ·{" "}
          {t("scene.holds")}: {draft.start_holds.length} · {t("scene.refs")}: {draft.ref_points.length}
        </p>
      </div>
      <div className="inspector-actions">
        <Button variant="glass" disabled={busy} onClick={() => onSave(draft)}>
          {t("scene.save")}
        </Button>
      </div>
      <label className="rating-field">
        {t("scene.copyFrom")}
        <select
          className="search-input"
          aria-label={t("scene.copyFrom")}
          value={copyId}
          onChange={(event) => setCopyId(event.target.value)}
        >
          <option value="">{t("scene.copyPick")}</option>
          {others.map((item) => (
            <option key={item.id} value={item.id}>
              {item.original_name || item.id}
            </option>
          ))}
        </select>
      </label>
      <Button variant="glass" disabled={!copyId || busy} onClick={() => onCopy(copyId)}>
        {t("scene.copy")}
      </Button>
    </section>
  );
}

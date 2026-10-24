import { useRef, useState } from "react";

import { t } from "../i18n/index.js";
import { clampPoint, clientToSource, pointInBBox } from "../lib/geometry.js";
import { HALPE26_NAMES, keypointSide } from "../lib/halpe26.js";
import { Button } from "./glass.jsx";

function nearestKeypoint(keypoints, x, y, maxDist = 24) {
  let best = -1;
  let bestDist = maxDist;
  (keypoints || []).forEach((point, index) => {
    if (!point) {
      return;
    }
    const dx = point[0] - x;
    const dy = point[1] - y;
    const dist = Math.hypot(dx, dy);
    if (dist < bestDist) {
      bestDist = dist;
      best = index;
    }
  });
  return best;
}

export function KeypointEditor({
  src,
  srcWidth = 0,
  srcHeight = 0,
  frame = 0,
  keypoints = [],
  persons = [],
  swapStart = 0,
  swapEnd = 0,
  onSwapRangeChange,
  onMove,
  onMoveEnd,
  onSwap,
  onInvalid,
  onConfirm,
  onSelectPerson,
}) {
  const stageRef = useRef(null);
  const dragRef = useRef(null);
  const [active, setActive] = useState(-1);

  function sourcePoint(event) {
    const rect = stageRef.current && stageRef.current.getBoundingClientRect();
    const raw = clientToSource(event.clientX, event.clientY, rect, srcWidth, srcHeight);
    return clampPoint(raw[0], raw[1], srcWidth, srcHeight);
  }

  function onPointerDown(event) {
    const [x, y] = sourcePoint(event);
    const person = (persons || []).find((item) => pointInBBox(x, y, item.bbox));
    if (person && onSelectPerson) {
      onSelectPerson(person);
      return;
    }
    const index = nearestKeypoint(keypoints, x, y);
    if (index < 0) {
      return;
    }
    dragRef.current = index;
    setActive(index);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event) {
    if (dragRef.current == null) {
      return;
    }
    const [x, y] = sourcePoint(event);
    onMove(dragRef.current, x, y);
  }

  function onPointerUp() {
    if (dragRef.current != null && onMoveEnd) {
      onMoveEnd(dragRef.current);
    }
    dragRef.current = null;
  }

  return (
    <section className="keypoint-editor" aria-label={t("skeleton.title")}>
      <div className="section-head">
        <h2 className="panel-title">{t("skeleton.title")}</h2>
        <span className="tabular">
          {t("queue.frame")} {frame}
        </span>
      </div>
      <div
        ref={stageRef}
        className="keypoint-stage"
        role="application"
        aria-label={t("skeleton.stage")}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        {src ? <img className="scene-frame" src={src} alt="" /> : null}
        <ul className="keypoint-dots">
          {(keypoints || []).map((point, index) =>
            point ? (
              <li
                key={HALPE26_NAMES[index] || index}
                className={`keypoint-dot keypoint-${keypointSide(index)}${active === index ? " is-on" : ""}`}
                style={{
                  left: `${srcWidth ? (point[0] / srcWidth) * 100 : 0}%`,
                  top: `${srcHeight ? (point[1] / srcHeight) * 100 : 0}%`,
                }}
              >
                <span className="sr-only">{HALPE26_NAMES[index] || index}</span>
              </li>
            ) : null,
          )}
        </ul>
      </div>
      <div className="swap-range">
        <label>
          {t("skeleton.swapStart")}
          <input
            className="search-input"
            type="number"
            aria-label={t("skeleton.swapStart")}
            value={swapStart}
            onChange={(event) => onSwapRangeChange([Number(event.target.value), swapEnd])}
          />
        </label>
        <label>
          {t("skeleton.swapEnd")}
          <input
            className="search-input"
            type="number"
            aria-label={t("skeleton.swapEnd")}
            value={swapEnd}
            onChange={(event) => onSwapRangeChange([swapStart, Number(event.target.value)])}
          />
        </label>
      </div>
      <div className="inspector-actions">
        <Button variant="glass" onClick={onSwap}>
          {t("skeleton.swap")}
        </Button>
        <Button variant="glass" onClick={onInvalid}>
          {t("skeleton.invalid")}
        </Button>
        <Button variant="glass" onClick={onConfirm}>
          {t("skeleton.confirm")}
        </Button>
      </div>
    </section>
  );
}

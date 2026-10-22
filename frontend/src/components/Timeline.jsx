import { useRef } from "react";

import { clampFrame } from "../lib/frameTime.js";
import { frameFromClientX } from "../lib/geometry.js";
import { formatTimecode } from "../lib/format.js";
import { t } from "../i18n/index.js";
import { Slider } from "./glass.jsx";

function tickStep(visible) {
  if (visible <= 30) {
    return 1;
  }
  if (visible <= 90) {
    return 5;
  }
  if (visible <= 300) {
    return 15;
  }
  if (visible <= 900) {
    return 30;
  }
  return 60;
}

export function Timeline({
  nFrames = 0,
  fps = 0,
  frame = 0,
  inFrame = 0,
  outFrame = 0,
  zoom = 1,
  onSeek,
  onInChange,
  onOutChange,
  onZoomChange,
}) {
  const trackRef = useRef(null);
  const max = Math.max(0, nFrames - 1);
  const visible = Math.max(1, Math.round((nFrames || 1) / Math.max(1, zoom)));
  const windowStart = clampFrame(frame - Math.floor(visible / 2), nFrames);
  const windowEnd = Math.min(max, windowStart + visible - 1);
  const span = Math.max(1, windowEnd - windowStart);
  const step = tickStep(visible);

  function ratio(value) {
    return `${((value - windowStart) / span) * 100}%`;
  }

  function seekFromEvent(event) {
    const rect = trackRef.current.getBoundingClientRect();
    const local = frameFromClientX(event.clientX, rect, visible);
    return clampFrame(windowStart + local, nFrames);
  }

  function startDrag(onChange) {
    return (event) => {
      event.preventDefault();
      event.stopPropagation();
      const move = (moveEvent) => onChange(seekFromEvent(moveEvent));
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      onChange(seekFromEvent(event));
    };
  }

  const ticks = [];
  const firstTick = Math.ceil(windowStart / step) * step;
  for (let value = firstTick; value <= windowEnd; value += step) {
    ticks.push(value);
  }

  return (
    <div className="timeline">
      <div className="timeline-meta">
        <span className="tabular">
          {t("timeline.in")} {inFrame}
        </span>
        <span className="tabular">
          {t("timeline.out")} {outFrame}
        </span>
        <label className="timeline-zoom">
          {t("timeline.zoom")}
          <Slider
            label={t("timeline.zoom")}
            min={1}
            max={16}
            step={1}
            value={zoom}
            onChange={onZoomChange}
          />
        </label>
      </div>
      <div
        ref={trackRef}
        className="timeline-track"
        role="slider"
        aria-label={t("timeline.playhead")}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={frame}
        onPointerDown={(event) => onSeek(seekFromEvent(event))}
      >
        <div
          className="timeline-range"
          style={{
            left: ratio(Math.min(inFrame, outFrame)),
            width: `${(Math.abs(outFrame - inFrame) / span) * 100}%`,
          }}
        />
        {ticks.map((value) => (
          <span key={value} className="timeline-tick tabular" style={{ left: ratio(value) }}>
            {formatTimecode(value, fps)}
          </span>
        ))}
        <button
          type="button"
          className="timeline-handle timeline-handle-in"
          style={{ left: ratio(inFrame) }}
          aria-label={t("timeline.in")}
          onPointerDown={startDrag(onInChange)}
        />
        <button
          type="button"
          className="timeline-handle timeline-handle-out"
          style={{ left: ratio(outFrame) }}
          aria-label={t("timeline.out")}
          onPointerDown={startDrag(onOutChange)}
        />
        <div className="timeline-playhead" style={{ left: ratio(frame) }} />
      </div>
    </div>
  );
}

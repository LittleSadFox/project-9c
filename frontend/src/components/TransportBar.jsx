import { formatFrameLabel } from "../lib/format.js";
import { t } from "../i18n/index.js";
import { Button, IconButton } from "./glass.jsx";

const MODES = [
  { id: "overlay", labelKey: "stage.overlay" },
  { id: "skeleton", labelKey: "stage.skeleton" },
  { id: "trails", labelKey: "stage.trails" },
];

export function TransportBar({
  playing,
  frame,
  fps,
  nFrames,
  rate,
  mode,
  onToggle,
  onStep,
  onRate,
  onMode,
}) {
  return (
    <div className="lg-glass transport-bar" role="group" aria-label={t("stage.transport")}>
      <IconButton label={t("stage.back10")} onClick={() => onStep(-10)}>
        ⏮
      </IconButton>
      <IconButton label={t("stage.back")} onClick={() => onStep(-1)}>
        ‹
      </IconButton>
      <Button variant="glass" onClick={onToggle}>
        {playing ? t("stage.pause") : t("stage.play")}
      </Button>
      <IconButton label={t("stage.forward")} onClick={() => onStep(1)}>
        ›
      </IconButton>
      <IconButton label={t("stage.forward10")} onClick={() => onStep(10)}>
        ⏭
      </IconButton>
      <div className="transport-readout tabular" aria-live="polite">
        {formatFrameLabel(frame || 0, fps)}
        {nFrames ? ` / ${nFrames - 1}` : ""}
      </div>
      <Button variant="glass" onClick={onRate}>
        {Math.abs(rate || 1)}×
        {rate < 0 ? " ◀" : ""}
      </Button>
      <div className="transport-modes">
        {MODES.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`transport-mode${mode === item.id ? " transport-mode-on" : ""}`}
            aria-pressed={mode === item.id}
            onClick={() => onMode(item.id)}
          >
            {t(item.labelKey)}
          </button>
        ))}
      </div>
    </div>
  );
}

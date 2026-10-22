import { t } from "../i18n/index.js";
import { Button, Slider } from "./glass.jsx";

const OUTCOMES = ["send", "fall", "unknown"];

export function RatingPanel({ value, onChange, saving = false, saved = false, error = null }) {
  const current = value || { outcome: "unknown", proximity: 0, exertion: 0, notes: "" };

  function update(patch) {
    onChange({ ...current, ...patch });
  }

  return (
    <form
      className="rating-panel"
      onSubmit={(event) => {
        event.preventDefault();
      }}
    >
      <h2 className="panel-title">{t("rating.title")}</h2>
      <div className="rating-outcomes" role="group" aria-label={t("rating.outcome")}>
        {OUTCOMES.map((outcome) => (
          <Button
            key={outcome}
            variant={current.outcome === outcome ? "primary" : "glass"}
            onClick={() => update({ outcome })}
          >
            {t(`outcome.${outcome}`)}
          </Button>
        ))}
      </div>
      <label className="rating-field">
        <span>
          {t("rating.proximity")} <span className="tabular">{current.proximity ?? 0}</span>
        </span>
        <Slider
          label={t("rating.proximity")}
          min={0}
          max={10}
          step={1}
          value={current.proximity ?? 0}
          onChange={(proximity) => update({ proximity })}
        />
      </label>
      <label className="rating-field">
        <span>
          {t("rating.exertion")} <span className="tabular">{current.exertion ?? 0}</span>
        </span>
        <Slider
          label={t("rating.exertion")}
          min={0}
          max={10}
          step={1}
          value={current.exertion ?? 0}
          onChange={(exertion) => update({ exertion })}
        />
      </label>
      <label className="rating-field">
        <span>{t("rating.notes")}</span>
        <textarea
          className="rating-notes"
          value={current.notes || ""}
          onChange={(event) => update({ notes: event.target.value })}
        />
      </label>
      <div className="rating-status" aria-live="polite">
        {error ? error : saving ? t("rating.saving") : saved ? t("rating.saved") : t("rating.autosave")}
      </div>
    </form>
  );
}

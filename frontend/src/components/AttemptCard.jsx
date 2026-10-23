import { Link } from "react-router";

import { t } from "../i18n/index.js";

export function AttemptCard({ attempt, selected = false, onSelect }) {
  return (
    <article className={`media-card media-card-attempt${selected ? " media-card-selected" : ""}`}>
      <button type="button" className="media-card-hit" onClick={() => onSelect && onSelect(attempt)}>
        <div className={`outcome-dot outcome-${attempt.outcome || "unknown"}`} />
        <div className="media-card-body">
          <div className="media-card-title">{t(`outcome.${attempt.outcome || "unknown"}`)}</div>
          <div className="media-card-meta tabular">
            {t("rating.proximity")} {attempt.proximity ?? "—"}
            {" · "}
            {t("rating.exertion")} {attempt.exertion ?? "—"}
          </div>
        </div>
      </button>
      <Link className="media-card-link" to={`/attempts/${attempt.id}`}>
        {t("action.openAttempt")}
      </Link>
    </article>
  );
}

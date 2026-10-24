import { t } from "../i18n/index.js";

export function ReviewQueue({ items = [], currentFrame, onJump }) {
  return (
    <section className="review-queue" aria-label={t("queue.title")}>
      <h2 className="panel-title">{t("queue.title")}</h2>
      {items.length === 0 ? <p className="sidebar-empty">{t("queue.empty")}</p> : null}
      <ul className="queue-list">
        {items.map((item) => (
          <li key={`${item.kind}-${item.frame}`}>
            <button
              type="button"
              className={`queue-row${item.frame === currentFrame ? " is-selected" : ""}`}
              onClick={() => onJump(item)}
            >
              <span className="tabular">{t("queue.frame")} {item.frame}</span>
              <span>{t(`queue.${item.kind || "low_score"}`)}</span>
              <span className="tabular">{item.score == null ? "" : item.score.toFixed(2)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

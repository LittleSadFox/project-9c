import { t } from "../i18n/index.js";

export function ProposalList({
  proposals = [],
  selectedId,
  checkedIds = [],
  onSelect,
  onToggle,
}) {
  if (proposals.length === 0) {
    return <p className="sidebar-empty">{t("proposals.empty")}</p>;
  }
  return (
    <ul className="proposal-list" aria-label={t("proposals.title")}>
      {proposals.map((item) => {
        const selected = item.id === selectedId;
        const checked = checkedIds.includes(item.id);
        return (
          <li key={item.id}>
            <div className={`proposal-row${selected ? " is-selected" : ""}`}>
              <input
                type="checkbox"
                checked={checked}
                aria-label={`${t("proposals.select")} ${item.id}`}
                onChange={() => onToggle(item.id)}
              />
              <button type="button" className="proposal-hit" onClick={() => onSelect(item)}>
                <span className="tabular">
                  {item.start_frame}–{item.end_frame}
                </span>
                <span>{t(`outcome.${item.outcome_guess || "unknown"}`)}</span>
                <span className="tabular">{Math.round((item.confidence || 0) * 100)}%</span>
                <span className="proposal-status">{t(`proposal.${item.status || "pending"}`)}</span>
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

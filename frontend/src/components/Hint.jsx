import { Tooltip } from "./glass.jsx";

export function Hint({ text }) {
  return (
    <Tooltip text={text}>
      <button type="button" className="lg-glass lg-icon-button" aria-label="Hint">
        ?
      </button>
    </Tooltip>
  );
}

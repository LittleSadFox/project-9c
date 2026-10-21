import { Hint } from "../components/Hint.jsx";
import { Panel } from "../components/glass.jsx";

export function EmptyPage({ title, copy, hint }) {
  return (
    <Panel>
      <article className="page">
        <h1 className="page-title">{title}</h1>
        <p className="page-copy">{copy}</p>
        {hint ? <Hint text={hint} /> : null}
      </article>
    </Panel>
  );
}

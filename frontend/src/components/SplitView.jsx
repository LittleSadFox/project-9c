export function SplitView({ sidebar, inspector, children, sidebarOpen = true, inspectorOpen = true }) {
  return (
    <div className="split-view">
      {sidebarOpen ? <aside className="split-sidebar">{sidebar}</aside> : null}
      <section className="split-content">{children}</section>
      {inspectorOpen ? <aside className="split-inspector">{inspector}</aside> : null}
    </div>
  );
}

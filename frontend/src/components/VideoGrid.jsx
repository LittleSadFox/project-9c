export function VideoGrid({ children, empty }) {
  if (!children || (Array.isArray(children) && children.length === 0)) {
    return <div className="grid-empty">{empty}</div>;
  }
  return <div className="media-grid">{children}</div>;
}

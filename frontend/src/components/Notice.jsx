export function Notice({ tone = "info", children }) {
  return (
    <div className={`notice notice-${tone}`} role="status">
      {children}
    </div>
  );
}

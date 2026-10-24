import { useId, useState } from "react";
import { NavLink } from "react-router";

export function TopBar({ children, className = "" }) {
  return <header className={`lg-glass lg-topbar ${className}`.trim()}>{children}</header>;
}

export function SegmentedNav({ items }) {
  return (
    <nav className="lg-glass lg-nav" aria-label="Primary">
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end}>
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function Tabs({ items, value, onChange }) {
  return (
    <div className="lg-glass lg-nav" role="tablist">
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className="lg-tab"
          role="tab"
          aria-selected={item.id === value}
          onClick={() => onChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function IconButton({ label, onClick, children }) {
  return (
    <button type="button" className="lg-glass lg-icon-button" aria-label={label} onClick={onClick}>
      {children}
    </button>
  );
}

export function Button({
  variant = "glass",
  type = "button",
  onClick,
  children,
  disabled = false,
  ...rest
}) {
  const extra =
    variant === "primary" ? "lg-button-primary" : variant === "danger" ? "lg-button-danger" : "";
  return (
    <button
      type={type}
      className={`lg-button ${extra}`.trim()}
      onClick={onClick}
      disabled={disabled}
      {...rest}
    >
      {children}
    </button>
  );
}

export function Switch({ checked, onChange, label }) {
  return (
    <button
      type="button"
      className="lg-switch"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
    />
  );
}

export function Slider({ value, min = 0, max = 1, step = 0.01, onChange, label }) {
  return (
    <input
      className="lg-slider"
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      aria-label={label}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  );
}

export function Panel({ children }) {
  return <section className="lg-panel">{children}</section>;
}

export function Sheet({ open, title, onClose, children }) {
  if (!open) {
    return null;
  }
  return (
    <div className="lg-sheet-root" role="presentation">
      <div className="lg-dimmer" onClick={onClose} />
      <div className="lg-glass-sheet" role="dialog" aria-modal="true" aria-label={title}>
        {children}
      </div>
    </div>
  );
}

export function Menu({ open, children }) {
  if (!open) {
    return null;
  }
  return <div className="lg-menu">{children}</div>;
}

export function Tooltip({ text, children }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  return (
    <span
      className="hint"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      {open ? (
        <span className="lg-tooltip hint-bubble" role="tooltip" id={id}>
          {text}
        </span>
      ) : null}
    </span>
  );
}

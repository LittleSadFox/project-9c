export function pad2(value) {
  return String(value).padStart(2, "0");
}

export function formatTimecode(frame, fps) {
  if (!fps) {
    return "00:00:00";
  }
  const total = Math.max(0, frame / fps);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = Math.floor(total % 60);
  if (hours > 0) {
    return `${hours}:${pad2(minutes)}:${pad2(seconds)}`;
  }
  return `${pad2(minutes)}:${pad2(seconds)}`;
}

export function formatFrameLabel(frame, fps) {
  return `${formatTimecode(frame, fps)} · ${frame}`;
}

export function formatPercent(value) {
  return `${Math.round((value || 0) * 100)}%`;
}

export function formatBytes(bytes) {
  if (!bytes) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

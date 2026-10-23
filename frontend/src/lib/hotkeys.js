const EDIT_TAGS = new Set(["input", "textarea", "select"]);

export function isEditableTarget(target) {
  if (!target) {
    return false;
  }
  const tag = String(target.tagName || "").toLowerCase();
  if (EDIT_TAGS.has(tag)) {
    return true;
  }
  return Boolean(target.isContentEditable);
}

export function interpretHotkey(event) {
  if (!event || isEditableTarget(event.target)) {
    return null;
  }
  const key = event.key;
  const meta = Boolean(event.metaKey || event.ctrlKey);
  if (meta && (key === "z" || key === "Z")) {
    return event.shiftKey ? "redo" : "undo";
  }
  if (meta) {
    return null;
  }
  if (key === " ") {
    return "toggle";
  }
  if (key === "ArrowLeft") {
    return event.shiftKey ? "stepBack10" : "stepBack";
  }
  if (key === "ArrowRight") {
    return event.shiftKey ? "stepForward10" : "stepForward";
  }
  if (key === "j" || key === "J") {
    return "reverse";
  }
  if (key === "k" || key === "K") {
    return "pause";
  }
  if (key === "l" || key === "L") {
    return "forward";
  }
  if (key === "i" || key === "I") {
    return "markIn";
  }
  if (key === "o" || key === "O") {
    return "markOut";
  }
  if (key === "Enter") {
    return "accept";
  }
  if (key === "Backspace" || key === "Delete") {
    return "reject";
  }
  if (key === "e" || key === "E") {
    return "editSkeleton";
  }
  if (key === "a" || key === "A") {
    return "addAnchor";
  }
  return null;
}

export function stepDelta(action) {
  if (action === "stepBack") {
    return -1;
  }
  if (action === "stepBack10") {
    return -10;
  }
  if (action === "stepForward") {
    return 1;
  }
  if (action === "stepForward10") {
    return 10;
  }
  return 0;
}

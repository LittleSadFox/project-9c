import { describe, expect, it } from "vitest";

import { interpretHotkey, isBlockedHotkeyTarget, isEditableTarget, stepDelta } from "./hotkeys.js";

function key(value, extra = {}) {
  return { key: value, target: { tagName: "BODY" }, ...extra };
}

describe("interpretHotkey", () => {
  it("maps Phase 1 transport keys", () => {
    expect(interpretHotkey(key(" "))).toBe("toggle");
    expect(interpretHotkey(key("ArrowLeft"))).toBe("stepBack");
    expect(interpretHotkey(key("ArrowRight"))).toBe("stepForward");
    expect(interpretHotkey(key("ArrowLeft", { shiftKey: true }))).toBe("stepBack10");
    expect(interpretHotkey(key("ArrowRight", { shiftKey: true }))).toBe("stepForward10");
    expect(interpretHotkey(key("j"))).toBe("reverse");
    expect(interpretHotkey(key("k"))).toBe("pause");
    expect(interpretHotkey(key("l"))).toBe("forward");
    expect(interpretHotkey(key("i"))).toBe("markIn");
    expect(interpretHotkey(key("o"))).toBe("markOut");
    expect(interpretHotkey(key("Enter"))).toBe("accept");
    expect(interpretHotkey(key("Delete"))).toBe("reject");
    expect(interpretHotkey(key("e"))).toBe("editSkeleton");
    expect(interpretHotkey(key("a"))).toBe("addAnchor");
  });

  it("maps undo and redo", () => {
    expect(interpretHotkey(key("z", { metaKey: true }))).toBe("undo");
    expect(interpretHotkey(key("z", { ctrlKey: true, shiftKey: true }))).toBe("redo");
  });

  it("ignores keys in an editable field", () => {
    expect(isEditableTarget({ tagName: "INPUT" })).toBe(true);
    expect(interpretHotkey(key(" ", { target: { tagName: "TEXTAREA" } }))).toBeNull();
  });

  it("ignores a focused button", () => {
    const target = { tagName: "BUTTON" };
    expect(isBlockedHotkeyTarget(target)).toBe(true);
    expect(interpretHotkey(key("Enter", { target }))).toBeNull();
    expect(interpretHotkey(key("Delete", { target }))).toBeNull();
  });

  it("ignores a focused link", () => {
    const target = { tagName: "A" };
    expect(isBlockedHotkeyTarget(target)).toBe(true);
    expect(interpretHotkey(key("Enter", { target }))).toBeNull();
  });

  it("ignores role=button", () => {
    const target = { tagName: "DIV", getAttribute: (name) => (name === "role" ? "button" : null) };
    expect(isBlockedHotkeyTarget(target)).toBe(true);
    expect(interpretHotkey(key("Enter", { target }))).toBeNull();
  });

  it("returns step deltas", () => {
    expect(stepDelta("stepBack10")).toBe(-10);
    expect(stepDelta("stepForward")).toBe(1);
  });
});

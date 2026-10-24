import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Sheet } from "../components/glass.jsx";
import { useHotkeys } from "./useHotkeys.js";

function Probe({ handlers, enabled = true, sheetOpen = false }) {
  useHotkeys(handlers, enabled);
  return (
    <div>
      <button type="button">Accept attempt</button>
      <a href="#open">Open video</a>
      <Sheet open={sheetOpen} title="Confirm reject" onClose={() => {}}>
        <p>This reject needs a confirm.</p>
      </Sheet>
    </div>
  );
}

describe("useHotkeys", () => {
  it("fires mapped handlers and ignores the notes field", () => {
    const toggle = vi.fn();
    function NotesProbe() {
      useHotkeys({ toggle }, true);
      return <input aria-label="Notes" />;
    }
    render(<NotesProbe />);
    fireEvent.keyDown(window, { key: " " });
    expect(toggle).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByLabelText("Notes"), { key: " " });
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it("skips Enter and Delete when a button is focused", () => {
    const accept = vi.fn();
    const reject = vi.fn();
    render(<Probe handlers={{ accept, reject }} />);
    const button = screen.getByRole("button", { name: "Accept attempt" });
    button.focus();
    fireEvent.keyDown(button, { key: "Enter" });
    fireEvent.keyDown(button, { key: "Delete" });
    expect(accept).not.toHaveBeenCalled();
    expect(reject).not.toHaveBeenCalled();
  });

  it("skips Enter when a link is focused", () => {
    const accept = vi.fn();
    render(<Probe handlers={{ accept }} />);
    const link = screen.getByRole("link", { name: "Open video" });
    link.focus();
    fireEvent.keyDown(link, { key: "Enter" });
    expect(accept).not.toHaveBeenCalled();
  });

  it("turns all hotkeys off while a confirm sheet is open", () => {
    const accept = vi.fn();
    const reject = vi.fn();
    render(<Probe handlers={{ accept, reject }} sheetOpen />);
    fireEvent.keyDown(window, { key: "Enter" });
    fireEvent.keyDown(window, { key: "Delete" });
    fireEvent.keyDown(document.body, { key: "Enter" });
    expect(accept).not.toHaveBeenCalled();
    expect(reject).not.toHaveBeenCalled();
  });
});

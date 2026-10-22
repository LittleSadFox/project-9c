import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useHotkeys } from "./useHotkeys.js";

function Probe({ handlers, enabled }) {
  useHotkeys(handlers, enabled);
  return <input aria-label="Notes" />;
}

describe("useHotkeys", () => {
  it("fires mapped handlers and ignores the notes field", () => {
    const toggle = vi.fn();
    render(<Probe handlers={{ toggle }} enabled />);
    fireEvent.keyDown(window, { key: " " });
    expect(toggle).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByLabelText("Notes"), { key: " " });
    expect(toggle).toHaveBeenCalledTimes(1);
  });
});

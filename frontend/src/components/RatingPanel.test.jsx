import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RatingPanel } from "./RatingPanel.jsx";

describe("RatingPanel", () => {
  it("emits outcome, ratings, and notes", () => {
    const onChange = vi.fn();
    render(
      <RatingPanel
        value={{ outcome: "unknown", proximity: 3, exertion: 4, notes: "" }}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(onChange).toHaveBeenCalledWith({ outcome: "send", proximity: 3, exertion: 4, notes: "" });
    fireEvent.change(screen.getByLabelText("Proximity"), { target: { value: "8" } });
    expect(onChange).toHaveBeenCalledWith({ outcome: "unknown", proximity: 8, exertion: 4, notes: "" });
    fireEvent.change(screen.getByLabelText("Exertion"), { target: { value: "1" } });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "heel hook" } });
    expect(onChange).toHaveBeenCalledWith({
      outcome: "unknown",
      proximity: 3,
      exertion: 4,
      notes: "heel hook",
    });
  });

  it("shows save state", () => {
    render(
      <RatingPanel
        value={{ outcome: "fall", proximity: 0, exertion: 0, notes: "" }}
        onChange={vi.fn()}
        saved
      />,
    );
    expect(screen.getByText("Saved")).toBeTruthy();
  });
});

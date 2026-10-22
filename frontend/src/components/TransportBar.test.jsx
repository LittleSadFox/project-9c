import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TransportBar } from "./TransportBar.jsx";

describe("TransportBar", () => {
  it("steps, toggles, and changes overlay mode", () => {
    const onToggle = vi.fn();
    const onStep = vi.fn();
    const onRate = vi.fn();
    const onMode = vi.fn();
    render(
      <TransportBar
        playing={false}
        frame={12}
        fps={30}
        nFrames={120}
        rate={1}
        mode="overlay"
        onToggle={onToggle}
        onStep={onStep}
        onRate={onRate}
        onMode={onMode}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    fireEvent.click(screen.getByRole("button", { name: "Forward one frame" }));
    fireEvent.click(screen.getByRole("button", { name: "Back ten frames" }));
    fireEvent.click(screen.getByRole("button", { name: "Skeleton" }));
    expect(onToggle).toHaveBeenCalled();
    expect(onStep).toHaveBeenCalledWith(1);
    expect(onStep).toHaveBeenCalledWith(-10);
    expect(onMode).toHaveBeenCalledWith("skeleton");
    expect(screen.getByText(/00:00 · 12/)).toBeTruthy();
  });
});

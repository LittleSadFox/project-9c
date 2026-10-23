import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Timeline } from "./Timeline.jsx";

describe("Timeline", () => {
  it("seeks from a track click and reports handle drags", () => {
    const onSeek = vi.fn();
    const onInChange = vi.fn();
    render(
      <Timeline
        nFrames={11}
        fps={30}
        frame={2}
        inFrame={1}
        outFrame={8}
        zoom={1}
        onSeek={onSeek}
        onInChange={onInChange}
        onOutChange={vi.fn()}
        onZoomChange={vi.fn()}
      />,
    );
    const track = screen.getByRole("slider", { name: "Playhead" });
    track.getBoundingClientRect = () => ({ left: 0, width: 100, top: 0, height: 20, right: 100, bottom: 20 });
    fireEvent.pointerDown(track, { clientX: 50 });
    expect(onSeek).toHaveBeenCalledWith(5);
    fireEvent.pointerDown(screen.getByRole("button", { name: "In" }), { clientX: 20 });
    expect(onInChange).toHaveBeenCalled();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { KeypointEditor } from "./KeypointEditor.jsx";
import { dummyFrame } from "../test/fixtures.js";

describe("KeypointEditor", () => {
  function renderEditor(handlers = {}) {
    const keypoints = dummyFrame();
    keypoints[5] = [100, 50, 0.9];
    const view = render(
      <KeypointEditor
        src="/api/videos/vid-1/frame?n=12&source=proxy"
        srcWidth={200}
        srcHeight={100}
        frame={12}
        keypoints={keypoints}
        persons={
          handlers.persons || [{ track_id: 1, bbox: [80, 20, 40, 40], keypoints: dummyFrame() }]
        }
        swapStart={10}
        swapEnd={20}
        onSwapRangeChange={handlers.onSwapRangeChange || vi.fn()}
        onMove={handlers.onMove || vi.fn()}
        onSwap={handlers.onSwap || vi.fn()}
        onInvalid={handlers.onInvalid || vi.fn()}
        onConfirm={handlers.onConfirm || vi.fn()}
        onSelectPerson={handlers.onSelectPerson || vi.fn()}
      />,
    );
    const stage = screen.getByRole("application", { name: "Skeleton stage" });
    stage.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100 });
    return { ...view, stage };
  }

  it("drags a keypoint and posts the tool actions", () => {
    const onMove = vi.fn();
    const onSwap = vi.fn();
    const onInvalid = vi.fn();
    const onConfirm = vi.fn();
    const { stage } = renderEditor({ onMove, onSwap, onInvalid, onConfirm, persons: [] });
    fireEvent.pointerDown(stage, { clientX: 100, clientY: 50 });
    fireEvent.pointerMove(stage, { clientX: 110, clientY: 60 });
    expect(onMove).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Swap L/R" }));
    fireEvent.click(screen.getByRole("button", { name: "Mark invalid" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm frame" }));
    expect(onSwap).toHaveBeenCalled();
    expect(onInvalid).toHaveBeenCalled();
    expect(onConfirm).toHaveBeenCalled();
  });

  it("clicks a person to pick the climber", () => {
    const onSelectPerson = vi.fn();
    const { stage } = renderEditor({ onSelectPerson });
    fireEvent.pointerDown(stage, { clientX: 90, clientY: 30 });
    expect(onSelectPerson).toHaveBeenCalledWith(expect.objectContaining({ track_id: 1, bbox: [80, 20, 40, 40] }));
  });
});

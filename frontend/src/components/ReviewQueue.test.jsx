import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReviewQueue } from "./ReviewQueue.jsx";
import { reviewQueueFixture } from "../test/fixtures.js";

describe("ReviewQueue", () => {
  it("jumps to a flagged frame", () => {
    const onJump = vi.fn();
    render(<ReviewQueue items={reviewQueueFixture} currentFrame={12} onJump={onJump} />);
    fireEvent.click(screen.getByRole("button", { name: /40/ }));
    expect(onJump).toHaveBeenCalledWith(reviewQueueFixture[1]);
  });
});

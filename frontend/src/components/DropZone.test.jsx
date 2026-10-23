import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DropZone } from "./DropZone.jsx";

describe("DropZone", () => {
  it("emits dropped files", () => {
    const onFiles = vi.fn();
    render(
      <DropZone onFiles={onFiles}>
        <div>grid</div>
      </DropZone>,
    );
    const file = new File([new Uint8Array([1])], "a.mov", { type: "video/quicktime" });
    fireEvent.drop(screen.getByText("grid").parentElement, {
      dataTransfer: { files: [file] },
    });
    expect(onFiles).toHaveBeenCalledWith([file]);
  });

  it("opens the file picker from Import", () => {
    render(<DropZone onFiles={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Import" })).toBeTruthy();
    expect(document.querySelector('input[type="file"]')).toBeTruthy();
  });
});

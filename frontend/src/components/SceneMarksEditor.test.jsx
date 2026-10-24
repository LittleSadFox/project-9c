import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { applySceneClick, SceneMarksEditor } from "./SceneMarksEditor.jsx";
import { sceneFixture, videoFixture } from "../test/fixtures.js";

describe("SceneMarksEditor", () => {
  it("adds floor points and saves the draft", () => {
    const onChange = vi.fn();
    const onSave = vi.fn();
    render(
      <SceneMarksEditor
        scene={sceneFixture}
        srcWidth={200}
        srcHeight={100}
        videos={[{ ...videoFixture, id: "vid-2", original_name: "other.mov" }]}
        currentVideoId="vid-1"
        onChange={onChange}
        onSave={onSave}
        onCopy={vi.fn()}
      />,
    );
    const stage = screen.getByRole("application", { name: "Scene stage" });
    stage.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100 });
    fireEvent.click(stage, { clientX: 20, clientY: 80 });
    expect(onChange).toHaveBeenCalled();
    expect(onChange.mock.calls[0][0].floor_line).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Save marks" }));
    expect(onSave).toHaveBeenCalledWith(sceneFixture);
  });

  it("copies marks from another video", () => {
    const onCopy = vi.fn();
    render(
      <SceneMarksEditor
        scene={sceneFixture}
        srcWidth={200}
        srcHeight={100}
        videos={[{ ...videoFixture, id: "vid-2", original_name: "other.mov" }]}
        currentVideoId="vid-1"
        onChange={vi.fn()}
        onSave={vi.fn()}
        onCopy={onCopy}
      />,
    );
    fireEvent.change(screen.getByLabelText("Copy from"), { target: { value: "vid-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Copy marks" }));
    expect(onCopy).toHaveBeenCalledWith("vid-2");
  });

  it("builds each mark kind from clicks", () => {
    expect(applySceneClick(sceneFixture, "zone", [1, 2]).top_zone.at(-1)).toEqual([1, 2]);
    expect(applySceneClick(sceneFixture, "holds", [3, 4]).start_holds.at(-1)).toEqual([3, 4]);
    expect(applySceneClick(sceneFixture, "refs", [5, 6], "lip").ref_points.at(-1)).toEqual({
      name: "lip",
      x: 5,
      y: 6,
    });
  });
});

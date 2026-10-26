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

  it("renders zero counts when auto scene arrays are null", () => {
    const partial = {
      floor_line: [
        [0, 0],
        [720, 0],
      ],
      top_zone: null,
      start_holds: null,
      ref_points: null,
      source: "auto",
    };
    expect(() =>
      render(
        <SceneMarksEditor
          scene={partial}
          srcWidth={200}
          srcHeight={100}
          videos={[]}
          currentVideoId="vid-1"
          onChange={vi.fn()}
          onSave={vi.fn()}
          onCopy={vi.fn()}
        />,
      ),
    ).not.toThrow();
    expect(screen.getByText(/Floor: 2/)).toBeTruthy();
    expect(screen.getByText(/Top zone: 0/)).toBeTruthy();
    expect(screen.getByText(/Start holds: 0/)).toBeTruthy();
    expect(screen.getByText(/Ref points: 0/)).toBeTruthy();
    expect(applySceneClick(partial, "zone", [1, 2]).top_zone).toEqual([[1, 2]]);
    expect(applySceneClick(partial, "holds", [3, 4]).start_holds).toEqual([[3, 4]]);
    expect(applySceneClick(partial, "refs", [5, 6], "lip").ref_points).toEqual([{ name: "lip", x: 5, y: 6 }]);
  });
});

import { useCallback } from "react";

import { getKeypoints } from "../api/pose.js";
import { useResource } from "./useResource.js";

const WINDOW = 120;

export function windowForFrame(frame) {
  const start = Math.max(0, Math.floor(frame / WINDOW) * WINDOW);
  return { start, end: start + WINDOW };
}

export function useKeypoints(videoId, frame, enabled) {
  const { start, end } = windowForFrame(frame || 0);
  const loader = useCallback(() => {
    if (!videoId || !enabled) {
      return Promise.resolve({ start, end, frames: [] });
    }
    return getKeypoints(videoId, { start, end, track: "climber", effective: true });
  }, [enabled, end, start, videoId]);
  return useResource(`keypoints:${videoId || "none"}:${start}:${end}:${enabled ? 1 : 0}`, loader);
}

export function frameKeypoints(payload, frame) {
  if (!payload || !payload.frames) {
    return null;
  }
  const start = payload.start || 0;
  const index = frame - start;
  if (index < 0 || index >= payload.frames.length) {
    return null;
  }
  return payload.frames[index];
}

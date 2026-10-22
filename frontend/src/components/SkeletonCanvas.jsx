import { useEffect, useRef } from "react";

import {
  clearCanvas,
  drawSkeleton,
  drawTrail,
  readSkeletonColors,
} from "../lib/drawSkeleton.js";
import { videoContentRect } from "../lib/geometry.js";
import { HALPE26_EDGES } from "../lib/halpe26.js";
import { useElementRect } from "../hooks/useElementRect.js";

export function SkeletonCanvas({
  videoRef,
  keypoints,
  trail = [],
  mode = "overlay",
  edges,
  srcWidth,
  srcHeight,
}) {
  const canvasRef = useRef(null);
  const hostRef = useRef(null);
  const rect = useElementRect(hostRef);

  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef && videoRef.current;
    if (!canvas) {
      return;
    }
    const width = rect.width || canvas.clientWidth;
    const height = rect.height || canvas.clientHeight;
    if (canvas.width !== width) {
      canvas.width = width;
    }
    if (canvas.height !== height) {
      canvas.height = height;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }
    clearCanvas(ctx, canvas.width, canvas.height);
    if (!keypoints && trail.length === 0) {
      return;
    }
    const content = videoContentRect(video);
    const options = {
      srcWidth: srcWidth || (video && video.videoWidth) || content.width,
      srcHeight: srcHeight || (video && video.videoHeight) || content.height,
      dstX: content.x,
      dstY: content.y,
      dstWidth: content.width,
      dstHeight: content.height,
      edges: edges || HALPE26_EDGES,
      colors: readSkeletonColors(),
    };
    if (mode === "trails") {
      drawTrail(ctx, trail, options);
    }
    drawSkeleton(ctx, keypoints, options);
  }, [edges, keypoints, mode, rect.height, rect.width, srcHeight, srcWidth, trail, videoRef]);

  return (
    <div ref={hostRef} className="skeleton-host">
      <canvas ref={canvasRef} className="skeleton-canvas" aria-hidden="true" />
    </div>
  );
}

import { edgeSide, HALPE26_EDGES, keypointSide } from "./halpe26.js";
import { scalePoint } from "./geometry.js";

export const DEFAULT_SKELETON_COLORS = {
  left: "#0a84ff",
  right: "#ff9f0a",
  center: "#8e8e93",
};

export function readSkeletonColors() {
  if (typeof document === "undefined") {
    return DEFAULT_SKELETON_COLORS;
  }
  const style = getComputedStyle(document.documentElement);
  return {
    left: style.getPropertyValue("--lg-color-primary").trim() || DEFAULT_SKELETON_COLORS.left,
    right: style.getPropertyValue("--lg-color-warn").trim() || DEFAULT_SKELETON_COLORS.right,
    center: style.getPropertyValue("--lg-color-grey").trim() || DEFAULT_SKELETON_COLORS.center,
  };
}

function pointAt(frame, index) {
  if (!frame || !frame[index]) {
    return null;
  }
  const [x, y, score] = frame[index];
  if (x === null || y === null) {
    return null;
  }
  return { x, y, score: score || 0 };
}

export function drawSkeleton(ctx, frame, options = {}) {
  const {
    srcWidth,
    srcHeight,
    dstX = 0,
    dstY = 0,
    dstWidth,
    dstHeight,
    edges = HALPE26_EDGES,
    colors = DEFAULT_SKELETON_COLORS,
    minScore = 0.3,
    lineWidth = 2,
  } = options;
  if (!ctx || !frame) {
    return;
  }

  const map = (x, y) => {
    const [sx, sy] = scalePoint(x, y, srcWidth, srcHeight, dstWidth, dstHeight);
    return [sx + dstX, sy + dstY];
  };

  for (const [a, b] of edges) {
    const pa = pointAt(frame, a);
    const pb = pointAt(frame, b);
    if (!pa || !pb) {
      continue;
    }
    const low = pa.score < minScore || pb.score < minScore;
    const [x1, y1] = map(pa.x, pa.y);
    const [x2, y2] = map(pb.x, pb.y);
    ctx.save();
    ctx.strokeStyle = colors[edgeSide(a, b)] || colors.center;
    ctx.lineWidth = lineWidth;
    ctx.setLineDash(low ? [6, 4] : []);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.restore();
  }

  frame.forEach((point, index) => {
    const item = pointAt(frame, index);
    if (!item) {
      return;
    }
    const [x, y] = map(item.x, item.y);
    ctx.save();
    ctx.fillStyle = colors[keypointSide(index)] || colors.center;
    ctx.globalAlpha = item.score < minScore ? 0.45 : 1;
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  });
}

export function drawTrail(ctx, frames, options = {}) {
  if (!ctx || !frames || frames.length === 0) {
    return;
  }
  frames.forEach((frame, index) => {
    const alpha = (index + 1) / frames.length;
    ctx.save();
    ctx.globalAlpha = alpha * 0.55;
    drawSkeleton(ctx, frame, { ...options, lineWidth: 1.5 });
    ctx.restore();
  });
}

export function clearCanvas(ctx, width, height) {
  if (!ctx) {
    return;
  }
  ctx.clearRect(0, 0, width, height);
}

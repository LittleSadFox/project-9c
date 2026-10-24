import { scalePoint } from "./geometry.js";

export function mapScenePoint(point, srcWidth, srcHeight, dstWidth, dstHeight, dstX = 0, dstY = 0) {
  const [x, y] = point || [];
  const [sx, sy] = scalePoint(x, y, srcWidth, srcHeight, dstWidth, dstHeight);
  return [sx + dstX, sy + dstY];
}

export function drawSceneMarks(ctx, scene, options = {}) {
  if (!ctx || !scene) {
    return;
  }
  const {
    srcWidth,
    srcHeight,
    dstX = 0,
    dstY = 0,
    dstWidth,
    dstHeight,
    colors = {},
  } = options;
  const map = (point) => mapScenePoint(point, srcWidth, srcHeight, dstWidth, dstHeight, dstX, dstY);

  if (scene.floor_line && scene.floor_line.length === 2) {
    const [a, b] = scene.floor_line.map(map);
    ctx.save();
    ctx.strokeStyle = colors.floor || "#8e8e93";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(a[0], a[1]);
    ctx.lineTo(b[0], b[1]);
    ctx.stroke();
    ctx.restore();
  }

  if (scene.top_zone && scene.top_zone.length >= 3) {
    const points = scene.top_zone.map(map);
    ctx.save();
    ctx.fillStyle = colors.zone || "rgba(10, 132, 255, 0.18)";
    ctx.strokeStyle = colors.zoneEdge || "#0a84ff";
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    points.slice(1).forEach(([x, y]) => ctx.lineTo(x, y));
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  for (const hold of scene.start_holds || []) {
    const [x, y] = map(hold);
    ctx.save();
    ctx.fillStyle = colors.hold || "#30d158";
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  for (const point of scene.ref_points || []) {
    const [x, y] = map([point.x, point.y]);
    ctx.save();
    ctx.fillStyle = colors.ref || "#ff9f0a";
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
}

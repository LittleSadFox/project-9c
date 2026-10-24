export function scalePoint(x, y, srcWidth, srcHeight, dstWidth, dstHeight) {
  if (!srcWidth || !srcHeight) {
    return [x, y];
  }
  return [(x / srcWidth) * dstWidth, (y / srcHeight) * dstHeight];
}

export function unscalePoint(x, y, srcWidth, srcHeight, dstWidth, dstHeight) {
  if (!dstWidth || !dstHeight) {
    return [x, y];
  }
  return [(x / dstWidth) * srcWidth, (y / dstHeight) * srcHeight];
}

export function videoContentRect(video) {
  if (!video) {
    return { x: 0, y: 0, width: 0, height: 0 };
  }
  const clientWidth = video.clientWidth || 0;
  const clientHeight = video.clientHeight || 0;
  const videoWidth = video.videoWidth || clientWidth;
  const videoHeight = video.videoHeight || clientHeight;
  if (!videoWidth || !videoHeight || !clientWidth || !clientHeight) {
    return { x: 0, y: 0, width: clientWidth, height: clientHeight };
  }
  const scale = Math.min(clientWidth / videoWidth, clientHeight / videoHeight);
  const width = videoWidth * scale;
  const height = videoHeight * scale;
  return {
    x: (clientWidth - width) / 2,
    y: (clientHeight - height) / 2,
    width,
    height,
  };
}

export function frameFromClientX(clientX, rect, nFrames) {
  if (!rect || !nFrames) {
    return 0;
  }
  const ratio = (clientX - rect.left) / Math.max(rect.width, 1);
  const max = nFrames - 1;
  return Math.max(0, Math.min(max, Math.round(ratio * max)));
}

export function clientToSource(clientX, clientY, rect, srcWidth, srcHeight) {
  if (!rect) {
    return [0, 0];
  }
  const localX = clientX - (rect.left || 0);
  const localY = clientY - (rect.top || 0);
  return unscalePoint(localX, localY, srcWidth, srcHeight, rect.width || 1, rect.height || 1);
}

export function clampPoint(x, y, width, height) {
  const maxX = Math.max(0, (width || 0) - 1);
  const maxY = Math.max(0, (height || 0) - 1);
  return [Math.max(0, Math.min(maxX, x)), Math.max(0, Math.min(maxY, y))];
}

export function pointInBBox(x, y, bbox) {
  if (!bbox || bbox.length < 4) {
    return false;
  }
  const [bx, by, bw, bh] = bbox;
  return x >= bx && y >= by && x <= bx + bw && y <= by + bh;
}

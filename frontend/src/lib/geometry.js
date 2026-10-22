export function scalePoint(x, y, srcWidth, srcHeight, dstWidth, dstHeight) {
  if (!srcWidth || !srcHeight) {
    return [x, y];
  }
  return [(x / srcWidth) * dstWidth, (y / srcHeight) * dstHeight];
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

export function clampFrame(frame, nFrames) {
  if (!nFrames || nFrames < 1) {
    return 0;
  }
  const value = Number.isFinite(frame) ? Math.round(frame) : 0;
  return Math.max(0, Math.min(nFrames - 1, value));
}

export function timeFromFrame(frame, fps) {
  if (!fps) {
    return 0;
  }
  return frame / fps;
}

export function frameFromTime(time, fps, nFrames) {
  if (!fps) {
    return 0;
  }
  return clampFrame(time * fps, nFrames);
}

export function stepFrame(frame, delta, nFrames) {
  return clampFrame(frame + delta, nFrames);
}

export function inOutValid(inFrame, outFrame, nFrames) {
  if (!nFrames || nFrames < 2) {
    return false;
  }
  return (
    Number.isInteger(inFrame) &&
    Number.isInteger(outFrame) &&
    inFrame >= 0 &&
    outFrame <= nFrames - 1 &&
    outFrame > inFrame
  );
}

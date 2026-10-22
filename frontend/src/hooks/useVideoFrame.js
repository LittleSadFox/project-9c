import { useEffect } from "react";

import { frameFromTime } from "../lib/frameTime.js";

export function useVideoFrame(videoRef, fps, nFrames, onFrame) {
  useEffect(() => {
    const video = videoRef && videoRef.current;
    if (!video || !fps) {
      return undefined;
    }

    let handle = 0;
    let raf = 0;
    let cancelled = false;

    const emit = (time) => {
      onFrame(frameFromTime(time, fps, nFrames));
    };

    const tick = (_now, metadata) => {
      if (cancelled) {
        return;
      }
      const time = metadata && metadata.mediaTime !== undefined ? metadata.mediaTime : video.currentTime;
      emit(time);
      if (video.requestVideoFrameCallback) {
        handle = video.requestVideoFrameCallback(tick);
      } else {
        raf = window.requestAnimationFrame(tick);
      }
    };

    const onTimeUpdate = () => emit(video.currentTime);

    if (video.requestVideoFrameCallback) {
      handle = video.requestVideoFrameCallback(tick);
    } else {
      video.addEventListener("timeupdate", onTimeUpdate);
      raf = window.requestAnimationFrame(tick);
    }

    return () => {
      cancelled = true;
      if (video.cancelVideoFrameCallback && handle) {
        video.cancelVideoFrameCallback(handle);
      }
      if (raf) {
        window.cancelAnimationFrame(raf);
      }
      video.removeEventListener("timeupdate", onTimeUpdate);
    };
  }, [videoRef, fps, nFrames, onFrame]);
}

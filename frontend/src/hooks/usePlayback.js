import { useCallback, useEffect, useRef, useState } from "react";

import { clampFrame, timeFromFrame } from "../lib/frameTime.js";
import { nextSignedRate } from "../lib/playback.js";
import { useVideoFrame } from "./useVideoFrame.js";

export function usePlayback({ fps = 0, nFrames = 0, startFrame = 0, endFrame = null } = {}) {
  const videoRef = useRef(null);
  const [frame, setFrame] = useState(startFrame);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const min = startFrame;
  const max = endFrame === null ? Math.max(0, (nFrames || 1) - 1) : endFrame;

  const seek = useCallback(
    (next, { resume = false } = {}) => {
      const clamped = clampFrame(Math.max(min, Math.min(max, next)), nFrames);
      setFrame(clamped);
      const video = videoRef.current;
      if (video && fps) {
        video.currentTime = timeFromFrame(clamped, fps);
        if (!resume && !video.paused) {
          video.pause();
          setPlaying(false);
        }
      }
      return clamped;
    },
    [fps, max, min, nFrames],
  );

  const applyRate = useCallback((nextRate) => {
    setRate(nextRate);
    const video = videoRef.current;
    if (video) {
      video.playbackRate = Math.abs(nextRate) || 1;
    }
  }, []);

  const play = useCallback(
    (nextRate = rate || 1) => {
      applyRate(nextRate);
      const video = videoRef.current;
      if (video) {
        const run = video.play();
        if (run && typeof run.catch === "function") {
          run.catch(() => {});
        }
      }
      setPlaying(true);
    },
    [applyRate, rate],
  );

  const pause = useCallback(() => {
    const video = videoRef.current;
    if (video) {
      video.pause();
    }
    setPlaying(false);
  }, []);

  const toggle = useCallback(() => {
    if (playing) {
      pause();
    } else {
      play(rate >= 0 ? rate || 1 : 1);
    }
  }, [pause, play, playing, rate]);

  const step = useCallback(
    (delta) => {
      pause();
      return seek(frame + delta);
    },
    [frame, pause, seek],
  );

  const reverse = useCallback(() => {
    const next = nextSignedRate(-1, playing ? rate : 0);
    play(next);
  }, [play, playing, rate]);

  const forward = useCallback(() => {
    const next = nextSignedRate(1, playing ? rate : 0);
    play(next);
  }, [play, playing, rate]);

  const onFrame = useCallback(
    (next) => {
      if (next >= max) {
        setFrame(max);
        if (playing) {
          pause();
          seek(max);
        }
        return;
      }
      if (next < min) {
        seek(min, { resume: true });
        return;
      }
      setFrame(next);
    },
    [max, min, pause, playing, seek],
  );

  useVideoFrame(videoRef, fps, nFrames, onFrame);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) {
      return undefined;
    }
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);
    return () => {
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
    };
  }, []);

  return {
    videoRef,
    frame,
    playing,
    rate,
    play,
    pause,
    toggle,
    seek,
    step,
    reverse,
    forward,
    setRate: applyRate,
  };
}

import { cycleRate } from "../lib/playback.js";
import { SkeletonCanvas } from "./SkeletonCanvas.jsx";
import { TransportBar } from "./TransportBar.jsx";
import { VideoStage } from "./VideoStage.jsx";

export function PlaybackPane({
  src,
  poster,
  playback,
  fps,
  nFrames,
  mode,
  onMode,
  keypoints,
  trail,
  edges,
  srcWidth,
  srcHeight,
}) {
  return (
    <VideoStage src={src} poster={poster} videoRef={playback.videoRef} hideVideo={mode === "skeleton"}>
      <SkeletonCanvas
        videoRef={playback.videoRef}
        keypoints={keypoints}
        trail={trail}
        mode={mode}
        edges={edges}
        srcWidth={srcWidth}
        srcHeight={srcHeight}
      />
      <div className="video-stage-transport">
        <TransportBar
          playing={playback.playing}
          frame={playback.frame}
          fps={fps}
          nFrames={nFrames}
          rate={playback.rate}
          mode={mode}
          onToggle={playback.toggle}
          onStep={playback.step}
          onRate={() => playback.setRate(cycleRate(playback.rate))}
          onMode={onMode}
        />
      </div>
    </VideoStage>
  );
}

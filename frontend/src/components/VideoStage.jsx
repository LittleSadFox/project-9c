export function VideoStage({
  src,
  poster,
  videoRef,
  hideVideo = false,
  onLoaded,
  children,
}) {
  return (
    <div className="video-stage">
      <video
        ref={videoRef}
        className={`video-stage-media${hideVideo ? " video-stage-hidden" : ""}`}
        src={src}
        poster={poster}
        playsInline
        preload="auto"
        controls={false}
        onLoadedMetadata={onLoaded}
      />
      <div className="video-stage-overlay">{children}</div>
    </div>
  );
}

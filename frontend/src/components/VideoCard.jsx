import { Link } from "react-router";

import { videoThumbUrl } from "../api/videos.js";
import { formatTimecode } from "../lib/format.js";
import { t } from "../i18n/index.js";

export function VideoCard({ video, selected = false, onSelect }) {
  const fps = video.fps || video.proxy_fps || 0;
  const duration = video.n_frames ? formatTimecode(video.n_frames, fps) : t("status.pending");
  return (
    <article className={`media-card${selected ? " media-card-selected" : ""}`}>
      <button type="button" className="media-card-hit" onClick={() => onSelect && onSelect(video)}>
        <img
          className="media-card-thumb"
          src={videoThumbUrl(video.id, 0)}
          alt=""
          onError={(event) => {
            event.currentTarget.style.visibility = "hidden";
          }}
        />
        <div className="media-card-body">
          <div className="media-card-title">{video.original_name}</div>
          <div className="media-card-meta tabular">
            {duration}
            {" · "}
            {t(`status.${video.ingest_status || "pending"}`)}
            {" / "}
            {t(`status.${video.pose_status || "pending"}`)}
          </div>
        </div>
      </button>
      <Link className="media-card-link" to={`/videos/${video.id}`}>
        {t("action.openVideo")}
      </Link>
    </article>
  );
}

import { request, toQuery } from "./client.js";

export function getPose(videoId) {
  return request(`/api/videos/${encodeURIComponent(videoId)}/pose`);
}

export function getKeypoints(videoId, params = {}) {
  const query = {
    track: params.track || "climber",
    effective: params.effective === false ? "false" : "true",
  };
  if (params.start !== undefined) {
    query.start = params.start;
  }
  if (params.end !== undefined) {
    query.end = params.end;
  }
  return request(`/api/videos/${encodeURIComponent(videoId)}/pose/keypoints${toQuery(query)}`);
}

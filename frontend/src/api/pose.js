import { request, toQuery } from "./client.js";
import { asList } from "../lib/lists.js";

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

export function getPersons(videoId, frame) {
  return request(
    `/api/videos/${encodeURIComponent(videoId)}/pose/persons${toQuery({ frame })}`,
  ).then(asList);
}

export function setClimber(videoId, body) {
  return request(`/api/videos/${encodeURIComponent(videoId)}/pose/climber`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function getReviewQueue(videoId) {
  return request(`/api/videos/${encodeURIComponent(videoId)}/pose/review-queue`).then(asList);
}

export function listPoseEdits(videoId, params = {}) {
  return request(`/api/videos/${encodeURIComponent(videoId)}/pose/edits${toQuery(params)}`).then(
    asList,
  );
}

export function createPoseEdit(videoId, body) {
  return request(`/api/videos/${encodeURIComponent(videoId)}/pose/edits`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function deletePoseEdit(videoId, editId) {
  return request(
    `/api/videos/${encodeURIComponent(videoId)}/pose/edits/${encodeURIComponent(editId)}`,
    { method: "DELETE" },
  );
}

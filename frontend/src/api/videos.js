import { request, toQuery, uploadFile } from "./client.js";

export function listVideos(params = {}) {
  return request(`/api/videos${toQuery(params)}`);
}

export function getVideo(id) {
  return request(`/api/videos/${encodeURIComponent(id)}`);
}

export function patchVideo(id, body) {
  return request(`/api/videos/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteVideo(id) {
  return request(`/api/videos/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function reprocessVideo(id, fromStage) {
  return request(`/api/videos/${encodeURIComponent(id)}/reprocess`, {
    method: "POST",
    body: JSON.stringify({ from_stage: fromStage }),
  });
}

export function uploadVideo(file, options = {}, onProgress) {
  const filename = options.filename || file.name;
  const params = { filename };
  if (options.boulder_id) {
    params.boulder_id = options.boulder_id;
  }
  if (options.session_id) {
    params.session_id = options.session_id;
  }
  if (options.last_modified) {
    params.last_modified = options.last_modified;
  } else if (file.lastModified) {
    params.last_modified = new Date(file.lastModified).toISOString();
  }
  return uploadFile(`/api/videos/upload${toQuery(params)}`, file, onProgress);
}

export function createAttempt(videoId, body) {
  return request(`/api/videos/${encodeURIComponent(videoId)}/attempts`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function createdAttemptId(payload) {
  if (payload && typeof payload.id === "string" && payload.id) {
    return payload.id;
  }
  throw new Error("Create attempt did not return a flat attempt id.");
}

export function videoProxyUrl(id) {
  return `/api/videos/${encodeURIComponent(id)}/proxy`;
}

export function videoOriginalUrl(id) {
  return `/api/videos/${encodeURIComponent(id)}/original`;
}

export function videoThumbUrl(id, index = 0) {
  return `/api/videos/${encodeURIComponent(id)}/thumb${toQuery({ i: index })}`;
}

export function videoFrameUrl(id, frame, source = "proxy") {
  return `/api/videos/${encodeURIComponent(id)}/frame${toQuery({ n: frame, source })}`;
}

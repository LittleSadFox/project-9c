import { request } from "./client.js";
import { emptyScene } from "../lib/lists.js";

const SCENE_WRITE_KEYS = ["floor_line", "top_zone", "start_holds", "ref_points"];

export function sceneWriteBody(scene) {
  const src = scene || {};
  const body = {};
  for (const key of SCENE_WRITE_KEYS) {
    body[key] = src[key] === undefined ? null : src[key];
  }
  return body;
}

export function getScene(videoId) {
  return request(`/api/videos/${encodeURIComponent(videoId)}/scene`);
}

export function putScene(videoId, body) {
  return request(`/api/videos/${encodeURIComponent(videoId)}/scene`, {
    method: "PUT",
    body: JSON.stringify(sceneWriteBody(body)),
  });
}

export function copySceneFrom(videoId, otherId) {
  return request(
    `/api/videos/${encodeURIComponent(videoId)}/scene/copy-from/${encodeURIComponent(otherId)}`,
    { method: "POST" },
  );
}

export function sceneOrEmpty(error) {
  if (error && (error.status === 404 || error.status === 501)) {
    return emptyScene();
  }
  throw error;
}

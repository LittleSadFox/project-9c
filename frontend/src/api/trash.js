import { request } from "./client.js";

export function listTrash() {
  return request("/api/trash");
}

export function restoreTrash(id) {
  return request(`/api/trash/${encodeURIComponent(id)}/restore`, { method: "POST" });
}

export function emptyTrash() {
  return request("/api/trash", { method: "DELETE" });
}

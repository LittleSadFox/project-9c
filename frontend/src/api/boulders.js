import { request, toQuery } from "./client.js";

export function listBoulders(params = {}) {
  return request(`/api/boulders${toQuery(params)}`);
}

export function getBoulder(id) {
  return request(`/api/boulders/${encodeURIComponent(id)}`);
}

export function createBoulder(body) {
  return request("/api/boulders", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function patchBoulder(id, body) {
  return request(`/api/boulders/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteBoulder(id) {
  return request(`/api/boulders/${encodeURIComponent(id)}`, { method: "DELETE" });
}

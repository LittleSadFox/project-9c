import { request, toQuery } from "./client.js";

export function listAttempts(params = {}) {
  return request(`/api/attempts${toQuery(params)}`);
}

export function getAttempt(id) {
  return request(`/api/attempts/${encodeURIComponent(id)}`);
}

export function patchAttempt(id, body) {
  return request(`/api/attempts/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function deleteAttempt(id) {
  return request(`/api/attempts/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function attemptClipUrl(id, version) {
  return `/api/attempts/${encodeURIComponent(id)}/clip${toQuery({ v: version })}`;
}

import { request, toQuery } from "./client.js";

export function listSessions(params = {}) {
  return request(`/api/sessions${toQuery(params)}`);
}

export function createSession(body) {
  return request("/api/sessions", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function patchSession(id, body) {
  return request(`/api/sessions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

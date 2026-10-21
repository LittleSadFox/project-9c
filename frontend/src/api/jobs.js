import { request } from "./client.js";

export function listJobs(state = "active") {
  return request(`/api/jobs?state=${encodeURIComponent(state)}`);
}

export function getJob(id) {
  return request(`/api/jobs/${encodeURIComponent(id)}`);
}

export function cancelJob(id) {
  return request(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

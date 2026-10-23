import { request } from "./client.js";

export function getSettings() {
  return request("/api/settings");
}

export function patchSettings(body) {
  return request("/api/settings", {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

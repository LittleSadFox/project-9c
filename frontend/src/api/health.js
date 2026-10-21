import { request } from "./client.js";

export function getHealth() {
  return request("/health");
}

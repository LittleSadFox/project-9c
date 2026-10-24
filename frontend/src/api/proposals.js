import { request } from "./client.js";
import { asList } from "../lib/lists.js";

export function listProposals(videoId) {
  return request(`/api/videos/${encodeURIComponent(videoId)}/proposals`).then(asList);
}

export function acceptProposal(proposalId, body = {}) {
  return request(`/api/proposals/${encodeURIComponent(proposalId)}/accept`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function rejectProposal(proposalId, reason = "not_attempt") {
  return request(`/api/proposals/${encodeURIComponent(proposalId)}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export function batchAcceptProposals(ids) {
  return request("/api/proposals/batch-accept", {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
}

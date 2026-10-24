import { pendingProposals } from "./lists.js";

export function nextPending(proposals, currentId) {
  const pending = pendingProposals(proposals);
  if (pending.length === 0) {
    return null;
  }
  const index = pending.findIndex((item) => item.id === currentId);
  if (index === -1) {
    return pending[0];
  }
  return pending[index + 1] || pending[0];
}

export function acceptPayload(proposal, inFrame, outFrame, outcome) {
  const body = {};
  if (!proposal) {
    return { start_frame: inFrame, end_frame: outFrame, outcome };
  }
  if (inFrame !== proposal.start_frame) {
    body.start_frame = inFrame;
  }
  if (outFrame !== proposal.end_frame) {
    body.end_frame = outFrame;
  }
  if (outcome) {
    body.outcome = outcome;
  }
  return body;
}

export function canFinishReview(proposals, reviewStatus) {
  if (reviewStatus === "reviewed") {
    return false;
  }
  return pendingProposals(proposals).length === 0;
}

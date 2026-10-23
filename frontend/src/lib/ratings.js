export function ratingsFrom(attempt) {
  return {
    outcome: attempt.outcome || "unknown",
    proximity: Number.isInteger(attempt.proximity) ? attempt.proximity : null,
    exertion: Number.isInteger(attempt.exertion) ? attempt.exertion : null,
    notes: attempt.notes || "",
  };
}

export function changedRatings(draft, current) {
  const from = ratingsFrom(current || {});
  const next = ratingsFrom(draft || {});
  const patch = {};
  if (next.outcome !== from.outcome) {
    patch.outcome = next.outcome;
  }
  if (next.notes !== from.notes) {
    patch.notes = next.notes;
  }
  if (next.proximity !== from.proximity && Number.isInteger(next.proximity)) {
    patch.proximity = next.proximity;
  }
  if (next.exertion !== from.exertion && Number.isInteger(next.exertion)) {
    patch.exertion = next.exertion;
  }
  return patch;
}

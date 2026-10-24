export function asList(payload) {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (payload && Array.isArray(payload.items)) {
    return payload.items;
  }
  return [];
}

export function emptyScene() {
  return {
    floor_line: [],
    top_zone: [],
    start_holds: [],
    ref_points: [],
    source: "auto",
  };
}

export function pendingProposals(proposals) {
  return asList(proposals).filter((item) => item && item.status === "pending");
}

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { invalidate, useResource } from "./useResource.js";

function Probe({ loader }) {
  const state = useResource("probe", loader);
  if (state.loading) {
    return <div>loading</div>;
  }
  if (state.error) {
    return <div>error</div>;
  }
  return <div>{state.data}</div>;
}

describe("useResource", () => {
  it("caches a loader result and refetches after invalidate", async () => {
    const loader = vi.fn()
      .mockResolvedValueOnce("one")
      .mockResolvedValueOnce("two");
    render(<Probe loader={loader} />);
    expect(await screen.findByText("one")).toBeTruthy();
    invalidate("probe");
    expect(await screen.findByText("two")).toBeTruthy();
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("surfaces a loader error", async () => {
    const loader = vi.fn().mockRejectedValue(new Error("nope"));
    render(<Probe loader={loader} />);
    expect(await screen.findByText("error")).toBeTruthy();
  });

  it("waits for a slow loader", async () => {
    const loader = vi.fn().mockResolvedValue("later");
    render(<Probe loader={loader} />);
    expect(screen.getByText("loading")).toBeTruthy();
    await waitFor(() => expect(screen.getByText("later")).toBeTruthy());
  });
});

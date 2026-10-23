import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { resetCache } from "../hooks/useResource.js";

afterEach(() => {
  cleanup();
  resetCache();
});

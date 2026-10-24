import { useEffect } from "react";

import { interpretHotkey, isModalOpen } from "../lib/hotkeys.js";

export function useHotkeys(handlers, enabled = true) {
  useEffect(() => {
    if (!enabled) {
      return undefined;
    }
    function onKeyDown(event) {
      if (isModalOpen()) {
        return;
      }
      const action = interpretHotkey(event);
      if (!action) {
        return;
      }
      const handler = handlers[action];
      if (!handler) {
        return;
      }
      event.preventDefault();
      handler(event);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handlers, enabled]);
}

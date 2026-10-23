import { useEffect, useRef } from "react";

export function useDebouncedCallback(callback, delay, deps) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      callbackRef.current();
    }, delay);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- caller passes the watched values
  }, [delay, ...deps]);
}

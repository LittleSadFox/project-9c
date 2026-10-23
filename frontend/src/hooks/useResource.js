import { useEffect, useRef, useState } from "react";

const cache = new Map();
const listeners = new Set();

function notify() {
  for (const listener of listeners) {
    listener();
  }
}

export function invalidate(prefix) {
  for (const key of [...cache.keys()]) {
    if (key.startsWith(prefix)) {
      cache.delete(key);
    }
  }
  notify();
}

export function resetCache() {
  cache.clear();
  notify();
}

export function useResource(key, loader) {
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const [state, setState] = useState(() => {
    if (cache.has(key)) {
      return { data: cache.get(key), error: null, loading: false };
    }
    return { data: null, error: null, loading: true };
  });

  useEffect(() => {
    let cancelled = false;
    let requestId = 0;

    async function load() {
      const id = ++requestId;
      if (cache.has(key)) {
        if (!cancelled) {
          setState({ data: cache.get(key), error: null, loading: false });
        }
        return;
      }
      if (!cancelled) {
        setState((current) => ({ ...current, loading: true }));
      }
      try {
        const data = await loaderRef.current();
        cache.set(key, data);
        if (!cancelled && id === requestId) {
          setState({ data, error: null, loading: false });
        }
      } catch (error) {
        if (!cancelled && id === requestId) {
          setState({ data: null, error, loading: false });
        }
      }
    }

    listeners.add(load);
    load();
    return () => {
      cancelled = true;
      listeners.delete(load);
    };
  }, [key]);

  return state;
}

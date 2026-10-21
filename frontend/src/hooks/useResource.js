import { useEffect, useState } from "react";

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

export function useResource(key, loader) {
  const [state, setState] = useState(() => {
    if (cache.has(key)) {
      return { data: cache.get(key), error: null, loading: false };
    }
    return { data: null, error: null, loading: true };
  });

  useEffect(() => {
    let cancelled = false;
    const onInvalidate = () => {
      if (!cache.has(key)) {
        setState((current) => ({ ...current, loading: true }));
      }
    };
    listeners.add(onInvalidate);
    if (!cache.has(key)) {
      loader()
        .then((data) => {
          cache.set(key, data);
          if (!cancelled) {
            setState({ data, error: null, loading: false });
          }
        })
        .catch((error) => {
          if (!cancelled) {
            setState({ data: null, error, loading: false });
          }
        });
    } else {
      setState({ data: cache.get(key), error: null, loading: false });
    }
    return () => {
      cancelled = true;
      listeners.delete(onInvalidate);
    };
  }, [key, loader]);

  return state;
}

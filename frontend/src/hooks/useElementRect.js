import { useLayoutEffect, useState } from "react";

export function useElementRect(ref) {
  const [rect, setRect] = useState({ width: 0, height: 0, left: 0, top: 0 });

  useLayoutEffect(() => {
    const node = ref && ref.current;
    if (!node) {
      return undefined;
    }

    const update = () => {
      const next = node.getBoundingClientRect();
      setRect({
        width: next.width,
        height: next.height,
        left: next.left,
        top: next.top,
      });
    };

    update();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", update);
      return () => window.removeEventListener("resize", update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref]);

  return rect;
}

import { useEffect, useState } from "react";

import { listJobs } from "../api/jobs.js";

function isActive(job) {
  return job.status === "queued" || job.status === "running";
}

export function useJobs() {
  const [jobs, setJobs] = useState([]);

  useEffect(() => {
    let cancelled = false;
    let timer = 0;

    async function tick() {
      let next = [];
      try {
        const active = await listJobs("active");
        next = active.items || [];
        if (next.length === 0) {
          const recent = await listJobs("recent");
          next = recent.items || [];
        }
      } catch {
        next = [];
      }
      if (cancelled) {
        return;
      }
      setJobs(next);
      const delay = next.some(isActive) ? 1000 : 5000;
      timer = window.setTimeout(tick, delay);
    }

    tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  return jobs;
}

import { cancelJob } from "../api/jobs.js";
import { useJobs } from "../hooks/useJobs.js";
import { t } from "../i18n/index.js";
import { Button } from "./glass.jsx";

export function JobTray() {
  const jobs = useJobs();
  const active = jobs.filter((job) => job.status === "queued" || job.status === "running");

  return (
    <div className="job-tray" aria-label={t("jobs.tray")}>
      {active.length === 0 ? (
        <div className="job-tray-meta">{t("jobs.empty")}</div>
      ) : (
        active.map((job) => (
          <div key={job.id} className="job-tray-item">
            <div>
              <div>{job.kind}</div>
              <div className="job-tray-meta tabular">
                {job.status} · {Math.round((job.progress || 0) * 100)}%
              </div>
            </div>
            <Button variant="glass" onClick={() => cancelJob(job.id)}>
              {t("jobs.cancel")}
            </Button>
          </div>
        ))
      )}
    </div>
  );
}

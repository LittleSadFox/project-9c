import { useCallback } from "react";
import { useNavigate } from "react-router";

import { getHealth } from "../api/health.js";
import { useResource } from "../hooks/useResource.js";
import { t } from "../i18n/index.js";
import { JobTray } from "./JobTray.jsx";
import { IconButton, SegmentedNav, TopBar } from "./glass.jsx";

const NAV = [
  { to: "/library", label: t("nav.library"), end: false },
  { to: "/compare", label: t("nav.compare"), end: false },
  { to: "/progress", label: t("nav.progress"), end: false },
  { to: "/models", label: t("nav.models"), end: true },
];

export function AppShell({ children }) {
  const navigate = useNavigate();
  const loadHealth = useCallback(() => getHealth(), []);
  const health = useResource("health", loadHealth);

  return (
    <div className="app-shell">
      <div className="app-shell-bar">
        <TopBar>
          <div className="lg-brand">{t("brand")}</div>
          {health.data && health.data.dev ? <span className="lg-dev-badge">{t("badge.dev")}</span> : null}
          <SegmentedNav items={NAV} />
        </TopBar>
        <div className="app-shell-tools">
          <JobTray />
          <IconButton label={t("action.settings")} onClick={() => navigate("/settings")}>
            ⚙
          </IconButton>
        </div>
      </div>
      <main className="app-main">{children}</main>
    </div>
  );
}

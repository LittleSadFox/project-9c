import { t } from "../i18n/index.js";
import { EmptyPage } from "./EmptyPage.jsx";

export function ProgressPage() {
  return <EmptyPage title={t("page.progress.title")} copy={t("page.progress.empty")} />;
}

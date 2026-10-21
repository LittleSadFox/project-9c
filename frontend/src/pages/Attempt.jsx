import { t } from "../i18n/index.js";
import { EmptyPage } from "./EmptyPage.jsx";

export function AttemptPage() {
  return <EmptyPage title={t("page.attempt.title")} copy={t("page.attempt.empty")} />;
}

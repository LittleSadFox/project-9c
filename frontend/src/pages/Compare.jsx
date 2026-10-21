import { t } from "../i18n/index.js";
import { EmptyPage } from "./EmptyPage.jsx";

export function ComparePage() {
  return <EmptyPage title={t("page.compare.title")} copy={t("page.compare.empty")} />;
}

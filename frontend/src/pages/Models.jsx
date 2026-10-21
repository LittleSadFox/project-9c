import { t } from "../i18n/index.js";
import { EmptyPage } from "./EmptyPage.jsx";

export function ModelsPage() {
  return <EmptyPage title={t("page.models.title")} copy={t("page.models.empty")} />;
}

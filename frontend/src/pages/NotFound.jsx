import { t } from "../i18n/index.js";
import { EmptyPage } from "./EmptyPage.jsx";

export function NotFoundPage() {
  return <EmptyPage title={t("page.notFound.title")} copy={t("page.notFound.empty")} />;
}

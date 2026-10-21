import { t } from "../i18n/index.js";
import { EmptyPage } from "./EmptyPage.jsx";

export function SettingsPage() {
  return <EmptyPage title={t("page.settings.title")} copy={t("page.settings.empty")} />;
}

import { t } from "../i18n/index.js";
import { EmptyPage } from "./EmptyPage.jsx";

export function LibraryPage() {
  return (
    <EmptyPage
      title={t("page.library.title")}
      copy={t("page.library.empty")}
      hint={t("hint.library")}
    />
  );
}

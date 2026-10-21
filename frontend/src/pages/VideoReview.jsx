import { t } from "../i18n/index.js";
import { EmptyPage } from "./EmptyPage.jsx";

export function VideoReviewPage() {
  return <EmptyPage title={t("page.video.title")} copy={t("page.video.empty")} />;
}

import { Component } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/AppShell.jsx";
import { t } from "./i18n/index.js";
import { AttemptPage } from "./pages/Attempt.jsx";
import { ComparePage } from "./pages/Compare.jsx";
import { LibraryPage } from "./pages/Library.jsx";
import { ModelsPage } from "./pages/Models.jsx";
import { NotFoundPage } from "./pages/NotFound.jsx";
import { ProgressPage } from "./pages/Progress.jsx";
import { SettingsPage } from "./pages/Settings.jsx";
import { VideoReviewPage } from "./pages/VideoReview.jsx";

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <main className="app-shell">
          <h1 className="page-title">{t("page.notFound.title")}</h1>
          <p className="page-copy">{String(this.state.error)}</p>
        </main>
      );
    }
    return this.props.children;
  }
}

export function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AppShell>
          <Routes>
            <Route path="/" element={<Navigate to="/library" replace />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/library/boulders/:boulderId" element={<LibraryPage />} />
            <Route path="/videos/:videoId" element={<VideoReviewPage />} />
            <Route path="/attempts/:attemptId" element={<AttemptPage />} />
            <Route path="/compare" element={<ComparePage />} />
            <Route path="/compare/:comparisonId" element={<ComparePage />} />
            <Route path="/progress" element={<ProgressPage />} />
            <Route path="/progress/:boulderId" element={<ProgressPage />} />
            <Route path="/models" element={<ModelsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </ErrorBoundary>
  );
}

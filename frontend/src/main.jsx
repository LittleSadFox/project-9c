import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App.jsx";
import "./theme/liquid-glass/tokens.css";
import "./theme/liquid-glass/glass.css";
import "./app.css";

const root = document.getElementById("root");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

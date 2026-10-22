import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

function previewApiStub() {
  return {
    name: "cc-preview-api-stub",
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url || "").split("?")[0];
        if (path === "/health") {
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              status: "ok",
              version: "0",
              db: "ok",
              ffmpeg: { version: "7", h264_encoder: "stub" },
              onnx: { providers: ["CPUExecutionProvider"], device: "cpu" },
              library_free_gb: 1,
              dev: false,
            }),
          );
          return;
        }
        if (path === "/api/jobs") {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ items: [], total: 0 }));
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), previewApiStub()],
  server: {
    host: "127.0.0.1",
    port: 8811,
    proxy: {
      "/api": "http://127.0.0.1:8810",
      "/auth": "http://127.0.0.1:8810",
      "/health": "http://127.0.0.1:8810",
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 8811,
  },
  build: {
    target: ["safari16", "chrome107"],
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.js", "src/**/*.test.jsx"],
    setupFiles: ["src/test/setup.js"],
  },
});

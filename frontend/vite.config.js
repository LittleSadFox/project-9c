import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
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
  },
});

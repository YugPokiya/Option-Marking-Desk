import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev: /api/* -> FastAPI on :8000 with the prefix stripped, exactly like Istio / nginx in production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.API_URL ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  test: { environment: "node" },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, the Vite dev server proxies /api to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8010" },
  },
  build: { outDir: "dist", sourcemap: false },
});

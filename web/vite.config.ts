import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The production build is written straight into the Python package so that
// `pip install openmuse` ships the app and `openmuse serve` can serve it.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../openmuse/server/static",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787",
      "/ws": { target: "ws://127.0.0.1:8787", ws: true },
    },
  },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * The dev server proxies to the API rather than talking cross-origin.
 *
 * Two reasons, and they are both about honesty in development: a token sent to
 * localhost:5173 and replayed against localhost:8123 is a different origin, so the browser
 * would need CORS allowances that the production deployment never uses (FastAPI serves the
 * built app itself). And `/geo` is a mount on the API, not a Vite asset, so without the proxy
 * the district boundaries would load in production and 404 in development - the kind of
 * difference that makes a demo fail in the room it is meant to impress.
 */
const API_TARGET = process.env.SANKET_API_TARGET ?? "http://127.0.0.1:8123";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
      "/geo": { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});

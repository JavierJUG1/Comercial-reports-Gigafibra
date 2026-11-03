import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// VITE_BASE_PATH: subruta de publicación (debe coincidir con BASE_PATH del backend). Vacío = raíz.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const base = (env.VITE_BASE_PATH || "").replace(/\/+$/, "");
  return {
    base: `${base}/`,
    plugins: [react()],
    server: {
      port: 5174,
      proxy: { [`${base}/api`]: { target: "http://127.0.0.1:8010", changeOrigin: false } },
    },
    build: { sourcemap: false, chunkSizeWarningLimit: 700 },
  };
});

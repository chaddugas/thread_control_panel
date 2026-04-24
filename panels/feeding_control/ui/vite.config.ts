import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

// Dev server defaults to localhost. To test from another machine on the LAN
// (e.g. Pi → Mac dev server, Mac → Pi-deployed bridge), pass --host.
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@thread-panel/ui-core": fileURLToPath(
        new URL("../../../platform/ui-core/src", import.meta.url),
      ),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});

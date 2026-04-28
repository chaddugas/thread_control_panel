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
    // ui-core lives outside this package's node_modules tree, so Rollup's
    // strict Node resolution can't find vue/pinia when bundling its files.
    // Dedupe forces these to resolve from the project root regardless of
    // where they're imported from — same instance everywhere, build works.
    dedupe: ["vue", "pinia"],
  },
  server: {
    port: 5173,
    strictPort: true,
  },
});

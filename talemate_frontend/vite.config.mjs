import { defineConfig, loadEnv } from "vite";
import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import vuetify from "vite-plugin-vuetify";
import runtimeEnv from "vite-plugin-runtime-env";

export default defineConfig(({ mode }) => {
  // Load env file based on `mode` in the current working directory.
  const env = loadEnv(mode, process.cwd(), "");
  const ALLOWED_HOSTS =
    (env.ALLOWED_HOSTS || "all") !== "all"
      ? env.ALLOWED_HOSTS.split(",")
      : "all";
  const VITE_TALEMATE_BACKEND_WEBSOCKET_URL =
    env.VITE_TALEMATE_BACKEND_WEBSOCKET_URL || null;

  console.log("NODE_ENV", env.NODE_ENV);
  console.log("ALLOWED_HOSTS", ALLOWED_HOSTS);
  console.log(
    "VITE_TALEMATE_BACKEND_WEBSOCKET_URL",
    VITE_TALEMATE_BACKEND_WEBSOCKET_URL
  );

  return {
    plugins: [vue(), vuetify({ autoImport: true }), runtimeEnv()],
    publicDir: "public",
    resolve: {
      alias: {
        // Use OS-native, decoded path for Windows compatibility (handles spaces)
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      // host: "0.0.0.0", // Make accessible from any network interface
      hmr: {
        overlay: false,
      },
      allowedHosts: ALLOWED_HOSTS,
    },
  };
});

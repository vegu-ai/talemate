import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // Use OS-native, decoded path for Windows compatibility (handles spaces)
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    // resolve `include` against this file's directory, not the cwd vitest ran from
    root: fileURLToPath(new URL(".", import.meta.url)),
    environment: "node",
    include: ["tests/unit/**/*.spec.js"],
  },
});

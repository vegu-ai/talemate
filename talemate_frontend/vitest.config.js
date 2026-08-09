import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
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

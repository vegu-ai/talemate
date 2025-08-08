import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";
import globals from "globals";

export default [
  {
    ignores: ["dist/**/*", "node_modules/**/*", "*.min.js"],
  },
  js.configs.recommended,
  ...pluginVue.configs["flat/essential"],
  {
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        node: true,
        ...globals.browser,
        ...globals.node,
      },
    },
    rules: {},
  },
];

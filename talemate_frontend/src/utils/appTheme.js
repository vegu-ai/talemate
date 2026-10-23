// The `app_config` broadcast is the only place a resolved theme reaches the
// running app, and it drives three independent sinks. Not every producer of
// that message resolves a theme, so an absent one has to leave all three where
// they are instead of resetting them to their defaults.

import { setActiveThemeColors } from "./messageColors.js";
import { setActiveCodeEditorTheme } from "./codeEditorTheme.js";
import { applyTheme } from "../plugins/vuetify";

export function applyAppConfigTheme(appConfig) {
  const resolvedTheme = appConfig?.theme;
  if (!resolvedTheme) {
    return false;
  }

  setActiveThemeColors(resolvedTheme.colors ?? null);
  setActiveCodeEditorTheme(resolvedTheme.code_editor ?? null);
  applyTheme(resolvedTheme);
  return true;
}

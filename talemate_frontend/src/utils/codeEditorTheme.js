// The ids mirror the `code_editor` Literal on the backend Theme model - a theme
// saved there names one of these, so the two lists have to stay in step.

import { computed, shallowRef } from "vue";
import { EditorView } from "@codemirror/view";
import { oneDark } from "@codemirror/theme-one-dark";
import {
  githubDark,
  githubLight,
  monokai,
  nord,
  solarizedLight,
  tokyoNightStorm,
  vsCodeLight,
} from "@fsegurai/codemirror-theme-bundle";

export const DEFAULT_CODE_EDITOR_THEME = "one-dark";

export const CODE_EDITOR_THEMES = [
  { value: "one-dark", title: "One Dark", dark: true },
  { value: "github-dark", title: "GitHub Dark", dark: true },
  { value: "monokai", title: "Monokai", dark: true },
  { value: "nord", title: "Nord", dark: true },
  { value: "tokyo-night-storm", title: "Tokyo Night Storm", dark: true },
  { value: "vscode-light", title: "VS Code Light", dark: false },
  { value: "github-light", title: "GitHub Light", dark: false },
  { value: "solarized-light", title: "Solarized Light", dark: false },
];

const CODE_EDITOR_THEME_EXTENSIONS = {
  "one-dark": oneDark,
  "github-dark": githubDark,
  monokai: monokai,
  nord: nord,
  "tokyo-night-storm": tokyoNightStorm,
  "vscode-light": vsCodeLight,
  "github-light": githubLight,
  "solarized-light": solarizedLight,
};

export function isCodeEditorTheme(id) {
  return Object.prototype.hasOwnProperty.call(CODE_EDITOR_THEME_EXTENSIONS, id);
}

// A null, absent or hand-built id resolves to the default rather than leaving
// an editor unstyled.
export function codeEditorThemeExtension(id) {
  const key = isCodeEditorTheme(id) ? id : DEFAULT_CODE_EDITOR_THEME;
  return CODE_EDITOR_THEME_EXTENSIONS[key];
}

const activeCodeEditorTheme = shallowRef(DEFAULT_CODE_EDITOR_THEME);

export function setActiveCodeEditorTheme(id) {
  activeCodeEditorTheme.value = isCodeEditorTheme(id) ? id : DEFAULT_CODE_EDITOR_THEME;
}

export function getActiveCodeEditorTheme() {
  return activeCodeEditorTheme.value;
}

// Components put this in their `extensions` array — vue-codemirror watches the
// prop and reconfigures the live editor, so open editors repaint on a change.
export const codeEditorTheme = computed(() => codeEditorThemeExtension(activeCodeEditorTheme.value));

// The `extensions` prop every codemirror host binds. `language` is built by the
// caller and held across recomputes — rebuilding it inside the getter would
// install a fresh LanguageSupport and re-parse the open document on every theme
// change.
export function codeEditorExtensions(language, ...extra) {
  return computed(() => [language, codeEditorTheme.value, EditorView.lineWrapping, ...extra]);
}

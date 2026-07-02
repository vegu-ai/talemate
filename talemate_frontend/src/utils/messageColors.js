// Scene-message color resolution.
//
// Single source of truth for the set of configurable "special" message color
// types and how their effective color/style is resolved from the user's
// appearance config. Mirrors talemate.util.colors.SPECIAL_COLOR_NAMES on the
// backend — keep in sync.

export const SPECIAL_MESSAGE_COLORS = [
  "narrator",
  "actor",
  "director",
  "time",
  "context_investigation",
  "information",
];

// Canonical default colors used both as the resolution fallback (when the
// user has not configured a color) and as the reset target in the appearance
// config UI. Keyed by bare type name — both message types (narrator, actor,
// director, time, context_investigation, information) and markup types
// (quotes, parentheses, brackets, emphasis, entities).
export const DEFAULT_APPEARANCE_COLORS = {
  narrator: "#A180AE",
  actor: "#B39DDB",
  director: "#FF5722",
  time: "#FFECB3",
  context_investigation: "#D5C0A1",
  information: "#BA8574",
  quotes: "#FFFFFF",
  parentheses: "#DB9DC2",
  brackets: "#DC5D5D",
  emphasis: "#B39DDB",
  entities: "#FFE082",
};

export function isSpecialMessageColor(name) {
  return SPECIAL_MESSAGE_COLORS.includes(name);
}

// Resolve the effective color for a scene-message type against the user's
// appearance config. Returns the configured color when set, otherwise the
// canonical default.
export function getMessageColor(appearanceConfig, typ) {
  const cfg = appearanceConfig?.scene?.[`${typ}_messages`];
  return cfg?.color || DEFAULT_APPEARANCE_COLORS[typ];
}

// Build an inline CSS style string (color + optional italic/bold) for a
// scene-message type from the user's appearance config.
export function getMessageStyle(appearanceConfig, typ) {
  const cfg = appearanceConfig?.scene?.[`${typ}_messages`] || {};
  let styles = "";
  if (cfg.italic) styles += "font-style: italic;";
  if (cfg.bold) styles += "font-weight: bold;";
  styles += `color: ${getMessageColor(appearanceConfig, typ)};`;
  return styles;
}

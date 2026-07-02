// Mirror of AUTOCOMPLETE_HINT_RE in src/talemate/util/dialogue.py.
// Used only for cosmetic textbox cleanup; the backend is the semantic source of truth.
export const AUTOCOMPLETE_HINT_RE = /\s*\{[^{}]+\}\s*$/;

// Append an autocomplete completion to a field, optionally stripping a trailing
// `{...}` hint block from the existing text first.
export function applyCompletion(current, completion, hintsEnabled) {
  const safe = String(current ?? '');
  const base = hintsEnabled ? safe.replace(AUTOCOMPLETE_HINT_RE, '') : safe;
  return base + completion;
}

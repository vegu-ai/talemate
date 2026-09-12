/**
 * Text-selection helpers for the "Add to world state" action in the chat view.
 *
 * The DOM work (reading the live Selection, resolving the message element)
 * lives in EntityHighlightMixin; everything here is string math so it can be
 * tested on its own.
 */

// Mirrors SNAPSHOT_ENTITY_SELECTION_MAX in
// src/talemate/agents/world_state/snapshot.py — the backend refuses anything
// longer, so the two numbers have to agree.
export const SELECTION_MAX_LENGTH = 240;

const WORD_CHARACTER = /[\p{L}\p{N}_'’-]/u;
const LEADING_NON_WORD = /^[^\p{L}\p{N}]+/u;
const TRAILING_NON_WORD = /[^\p{L}\p{N}]+$/u;

export function isWordCharacter(character) {
    return typeof character === 'string' && WORD_CHARACTER.test(character);
}

/**
 * Widen [start, end) until neither edge cuts a word in half. A selection that
 * starts inside "beacon" grows to cover the whole word rather than losing it,
 * which is also what the highlight matcher needs: it only matches phrases on
 * word boundaries.
 */
export function snapOffsetsToWords(text, start, end) {
    const source = typeof text === 'string' ? text : '';
    let from = Math.max(0, Math.min(start, source.length));
    let to = Math.max(from, Math.min(end, source.length));
    while (from > 0 && isWordCharacter(source[from - 1]) && isWordCharacter(source[from])) {
        from -= 1;
    }
    while (to < source.length && isWordCharacter(source[to]) && isWordCharacter(source[to - 1])) {
        to += 1;
    }
    return [from, to];
}

/** Collapse the whitespace of a raw selection and drop its outer punctuation. */
export function normalizeSelectionText(raw) {
    return String(raw || '')
        .replace(/\s+/g, ' ')
        .trim()
        .replace(LEADING_NON_WORD, '')
        .replace(TRAILING_NON_WORD, '');
}

/**
 * Turn a raw selection into the text to send and, when it cannot be sent, the
 * reason the caller reports instead. "empty" means there is nothing to act on
 * and no card is worth showing.
 */
export function evaluateSelection(raw) {
    const text = normalizeSelectionText(raw);
    if (!text) {
        return { reason: 'empty', text: '' };
    }
    if (text.length > SELECTION_MAX_LENGTH) {
        return { reason: 'too-long', text };
    }
    return { reason: null, text };
}

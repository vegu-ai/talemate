export const CURATED_ICONS = [
    'mdi-lightning-bolt',
    'mdi-dice-multiple',
    'mdi-drama-masks',
    'mdi-script-text',
    'mdi-book-open-page-variant',
    'mdi-account-voice',
    'mdi-chat-question',
    'mdi-compass-rose',
    'mdi-map-search',
    'mdi-door-open',
    'mdi-treasure-chest',
    'mdi-sword-cross',
    'mdi-bow-arrow',
    'mdi-shield-sword',
    'mdi-skull',
    'mdi-heart',
    'mdi-heart-broken',
    'mdi-fire',
    'mdi-weather-night',
    'mdi-auto-fix',
    'mdi-crystal-ball',
    'mdi-ghost',
    'mdi-eye',
    'mdi-ear-hearing',
];

export const MDI_LISTING_URL = 'https://pictogrammers.com/library/mdi/';

// Shape of a valid MDI icon name. This only checks the name looks like an mdi
// class — whether the glyph exists in the shipped webfont can only be answered
// by rendering it (see IconPicker.vue).
export const ICON_VALID_RE = /^mdi-[a-z0-9]+(-[a-z0-9]+)*$/;

export function isValidIconName(name) {
    return typeof name === 'string' && ICON_VALID_RE.test(name);
}

/**
 * Shortcuts of one scene tool section, paired with their catalog entry, in
 * insertion order. A shortcut whose action is not in the catalog is dropped:
 * the action it points at no longer exists in this build.
 */
export function shortcutsForSection(shortcuts, catalog, section) {
    const entries = new Map((catalog || []).map(entry => [entry.id, entry]));
    return Object.values(shortcuts || {})
        .map(shortcut => ({ shortcut, entry: entries.get(shortcut.action_id) }))
        .filter(row => row.entry && row.entry.section === section);
}

/**
 * Flattens a section's shortcuts into renderable rows. A per-character action
 * becomes one row per entry in `characters` (each section passes the character
 * set its native menu uses), and `include_unbound` adds a leading row that runs
 * the action without a character. A per-character action with nobody to target
 * still gets one `unavailable` row, so the shortcut stays visible and editable.
 */
export function expandShortcutEntries(shortcuts, catalog, section, characters) {
    const names = characters || [];
    const rows = [];

    for (const { shortcut, entry } of shortcutsForSection(shortcuts, catalog, section)) {
        if (!entry.per_character || entry.include_unbound) {
            rows.push({ key: rowKey(shortcut, null), shortcut, entry, character: null });
        }
        if (!entry.per_character) {
            continue;
        }
        if (!names.length && !entry.include_unbound) {
            rows.push({ key: rowKey(shortcut, null), shortcut, entry, character: null, unavailable: true });
            continue;
        }
        for (const character of names) {
            rows.push({ key: rowKey(shortcut, character), shortcut, entry, character });
        }
    }

    return rows;
}

function rowKey(shortcut, character) {
    return `${shortcut.uid}:${character || ''}`;
}

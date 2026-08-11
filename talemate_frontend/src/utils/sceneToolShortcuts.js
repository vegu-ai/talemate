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
 * Installable `scene_tool_shortcut` templates of one scene tool section, paired
 * with their catalog entry. `templates` is the `by_type.scene_tool_shortcut`
 * map, keyed by `groupUid__templateUid`. A template whose action is not in the
 * catalog is dropped, the same way an orphaned shortcut is.
 */
export function shortcutTemplatesForSection(templates, catalog, section) {
    const entries = new Map((catalog || []).map(entry => [entry.id, entry]));
    return Object.entries(templates || {})
        .map(([key, template]) => ({ key, template, entry: entries.get(template.action_id) }))
        .filter(row => row.entry && row.entry.section === section);
}

/**
 * The `scene_tool_shortcut` template a shortcut is shared as. `group` is the
 * uid of the group it is saved into, `uid` a fresh template id.
 */
export function shortcutAsTemplate(shortcut, group, uid) {
    const label = (shortcut.label || '').trim();
    return {
        uid,
        name: label,
        template_type: 'scene_tool_shortcut',
        group,
        action_id: shortcut.action_id,
        label,
        icon: shortcut.icon,
        instructions: shortcut.instructions || '',
        favorite: false,
        priority: 1,
    };
}

/**
 * The `world_state_manager` message that installs a `scene_tool_shortcut`
 * template as a shortcut. Never runs the action it points at.
 */
export function applyShortcutTemplateMessage(template) {
    return {
        type: 'world_state_manager',
        action: 'apply_template',
        template,
        character_name: null,
        run_immediately: false,
    };
}

/**
 * The next step of a "save shortcut as template" round trip, given the pending
 * save and an incoming message. A group-less pending save waits for the echo of
 * the group it created — matched by the uid the request minted, since nothing
 * makes a group name unique to one request — then goes out as a template save;
 * the template echo (matched by uid) ends it. A failed save is only ever
 * announced as an `operation_done` carrying an error and our request id: the
 * success envelopes of these handlers carry no request id at all.
 */
export function templateSaveTransition(pending, message) {
    if (!pending || !message || message.type !== 'world_state_manager') {
        return { op: 'ignore' };
    }

    if (message.action === 'operation_done') {
        const error = message.error;
        if (!error || !pending.requestId || message.request_id !== pending.requestId) {
            return { op: 'ignore' };
        }
        return { op: 'fail', message: error.message || 'The template could not be saved.' };
    }

    if (message.action === 'template_group_saved' && !pending.template.group) {
        const group = (message.data || {}).group;
        if (!group || !pending.groupUid || group.uid !== pending.groupUid) {
            return { op: 'ignore' };
        }
        return { op: 'send-template', template: { ...pending.template, group: group.uid } };
    }

    if (message.action === 'template_saved') {
        const template = (message.data || {}).template;
        if (!template || template.uid !== pending.template.uid) {
            return { op: 'ignore' };
        }
        return { op: 'complete' };
    }

    return { op: 'ignore' };
}

/**
 * The file stem the backend derives a template group's file from.
 */
function templateGroupSlug(name) {
    return (name || '').trim().replace(/ /g, '-').toLowerCase();
}

/**
 * The group a typed group name refers to, or null when it names a new one.
 * Matched on the derived file name rather than the display name: a group named
 * `my-shortcuts` and one named `My Shortcuts` would fight over the same file.
 */
export function templateGroupByName(groups, name) {
    const wanted = templateGroupSlug(name);
    if (!wanted) {
        return null;
    }
    return (groups || []).find(group => templateGroupSlug(group.name) === wanted) || null;
}

/**
 * Vuetify rule for a template group name: the name becomes a file name, so it
 * may carry neither a path separator nor any character Windows refuses, and it
 * may not be dots or whitespace alone.
 */
export function validateGroupName(value) {
    if (value == null) {
        return true;
    }
    if (/[<>:"/\\|?*]/.test(value)) {
        return "Name contains invalid characters";
    }
    if (/^[.\s]+$/.test(value)) {
        return "Name contains invalid characters";
    }
    return true;
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

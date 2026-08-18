/**
 * Template icon and color mappings
 * Used for displaying template types consistently across the application
 */

import { DEFAULT_APPEARANCE_COLORS } from './messageColors.js';
import { DEFAULT_CODE_EDITOR_THEME, isCodeEditorTheme } from './codeEditorTheme.js';

const THEME_APP_SLOTS = [
    'primary',
    'secondary',
    'delete',
    'cancel',
    'muted',
    'mutedheader',
    'mutedbg',
    'normal',
    'unsaved',
    'favorite',
    'dirty',
    'persona',
    'highlight1',
    'highlight2',
    'highlight3',
    'highlight4',
    'highlight5',
    'highlight6',
    'highlight7',
    'inactive',
    'module_selected',
    'module_locked_selected',
    'success',
    'info',
    'warning',
    'error',
];

/**
 * The color slots of a `theme` template, grouped by the area they paint. The
 * groups are the editing surface: one flat list of every slot is unusable.
 */
export const THEME_COLOR_GROUPS = [
    {
        key: 'app',
        title: 'App',
        icon: 'mdi-application-outline',
        slots: THEME_APP_SLOTS,
    },
    {
        key: 'surfaces',
        title: 'Surfaces',
        icon: 'mdi-layers-outline',
        slots: [
            'background',
            'surface',
            'surface_bright',
            'surface_light',
            'surface_variant',
            'on_surface_variant',
        ],
    },
    {
        key: 'messages',
        title: 'Messages',
        icon: 'mdi-message-text-outline',
        slots: [
            'narrator',
            'actor',
            'director',
            'time',
            'context_investigation',
            'information',
            'quotes',
            'parentheses',
            'brackets',
            'emphasis',
            'entities',
            'play_audio',
            'border',
            'defaultBadge',
        ],
    },
    {
        key: 'chats',
        title: 'Chats',
        icon: 'mdi-forum-outline',
        slots: [
            'dchat_msg_director',
            'dchat_msg_action_result',
            'dchat_msg_compaction',
            'hchat_msg_help',
            'hchat_msg_doc_result',
        ],
    },
];

// message and markup types of a theme's appearance block, with the flags each
// of them carries beyond italic/bold
const THEME_APPEARANCE_TYPES = {
    narrator: {},
    actor: {},
    director: { show: true },
    time: {},
    context_investigation: { show: true },
    information: {},
    quotes: { override_color: true, show: true },
    parentheses: { italic: false, override_color: true, show: true },
    brackets: { italic: false, override_color: true, show: true },
    emphasis: { italic: false, override_color: true, show: true },
    entities: { override_color: true, show: true },
};

/**
 * The styling flags an appearance entry can carry, with the name each is shown
 * under. Every surface that offers them - the theme editor's appearance table
 * and the preview's element popup - reads this, so a flag added here appears in
 * both under one name.
 */
export const APPEARANCE_STYLE_FLAGS = [
    { key: 'italic', label: 'Italic' },
    { key: 'bold', label: 'Bold' },
    { key: 'show', label: 'Show' },
    { key: 'override_color', label: 'Own color' },
];

/**
 * Theme appearance key -> scene appearance key, mirroring the backend's
 * `THEME_APPEARANCE_MAP`.
 */
export const THEME_APPEARANCE_MAP = {
    narrator: 'narrator_messages',
    actor: 'actor_messages',
    director: 'director_messages',
    time: 'time_messages',
    context_investigation: 'context_investigation_messages',
    information: 'information_messages',
    quotes: 'quotes',
    parentheses: 'parentheses',
    brackets: 'brackets',
    emphasis: 'emphasis',
    entities: 'entities',
    backdrop_panel_opacity: 'backdrop_panel_opacity',
    backdrop_text_shadow: 'backdrop_text_shadow',
};

const THEME_SLOT_LABELS = {
    mutedheader: 'Muted header',
    mutedbg: 'Muted background',
    // the template's own `favorite` field sits next to this slot — the label has
    // to say which of the two is meant
    favorite: 'Favorite marker',
    module_selected: 'Selected node module',
    module_locked_selected: 'Selected locked node module',
    border: 'Avatar and card borders',
    defaultBadge: 'Default asset badge',
};

const THEME_SLOT_PREFIXES = {
    dchat: 'Director chat',
    hchat: 'Help chat',
};

export function iconForTemplate(template) {
    const templateType = template.template_type;
    
    if (templateType == 'character_attribute') {
        return 'mdi-badge-account';
    } else if (templateType == 'character_detail') {
        return 'mdi-account-details';            
    } else if (templateType == 'state_reinforcement') {
        return 'mdi-image-auto-adjust';
    } else if (templateType == 'spices') {
        return 'mdi-chili-mild';
    } else if (templateType == 'writing_style') {
        return 'mdi-script-text';
    } else if (templateType == 'visual_style') {
        return 'mdi-palette';
    } else if (templateType == 'visual_finalizer') {
        return 'mdi-auto-fix';
    } else if (templateType == 'agent_persona') {
        return 'mdi-drama-masks';
    } else if (templateType == 'scene_type') {
        return 'mdi-movie-open';
    } else if (templateType == 'scene_tool_shortcut') {
        return 'mdi-lightning-bolt';
    } else if (templateType == 'theme') {
        return 'mdi-palette-swatch';
    }
    return 'mdi-cube-scan';
}

// template attribute holding the template's row list, per template type —
// used by the table widget's insert-preset control
export function rowsFieldForTemplateType(templateType) {
    return { visual_finalizer: 'finalizers' }[templateType];
}

export function colorForTemplate(template) {
    const templateType = template.template_type;
    
    if (templateType == 'character_attribute') {
        return 'highlight1';
    } else if (templateType == 'character_detail') {
        return 'highlight2';
    } else if (templateType == 'state_reinforcement') {
        return 'highlight3';
    } else if (templateType == 'spices') {
        return 'highlight4';
    } else if (templateType == 'writing_style') {
        return 'highlight5';
    } else if (templateType == 'visual_style') {
        return 'highlight5';
    } else if (templateType == 'visual_finalizer') {
        return 'highlight5';
    } else if (templateType == 'agent_persona') {
        return 'persona';
    } else if (templateType == 'scene_type') {
        return 'highlight6';
    } else if (templateType == 'scene_tool_shortcut') {
        return 'highlight7';
    } else if (templateType == 'theme') {
        return 'secondary';
    }
    return 'muted';
}

/**
 * The name vuetify knows a theme color slot by. The surface slots are declared
 * with underscores because the backend model fields cannot carry a hyphen,
 * while vuetify's own base slots are hyphenated (`surface-bright`).
 */
export function vuetifySlotName(groupKey, slot) {
    return groupKey === 'surfaces' ? slot.replace(/_/g, '-') : slot;
}

function sentenceCase(words) {
    const text = words.join(' ').toLowerCase();
    return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * A readable label for a theme color slot or appearance type, derived from its
 * name: camel case and underscores become word breaks, a trailing number is
 * split off, and a chat prefix names its chat.
 */
export function labelForThemeSlot(slot) {
    if (THEME_SLOT_LABELS[slot]) {
        return THEME_SLOT_LABELS[slot];
    }
    let words = slot
        .replace(/([a-z])([A-Z])/g, '$1 $2')
        .replace(/([a-z])(\d+)$/, '$1 $2')
        .split(/[_ ]+/);

    const prefix = THEME_SLOT_PREFIXES[words[0]];
    if (prefix) {
        words = words.slice(1).filter(word => word !== 'msg');
        return `${prefix} · ${sentenceCase(words)}`;
    }
    return sentenceCase(words);
}

/**
 * A `#RRGGBB` string, or null when the value is not one. Also trims the alpha
 * off the `#RRGGBBAA` the color picker can hand back.
 */
export function normalizeHexColor(value) {
    if (typeof value !== 'string') {
        return null;
    }
    const match = value.trim().match(/^#[0-9a-fA-F]{6}/);
    return match ? match[0] : null;
}

function defaultThemeColor(groupKey, slot, themeColors) {
    return (
        normalizeHexColor((themeColors || {})[vuetifySlotName(groupKey, slot)]) ||
        DEFAULT_APPEARANCE_COLORS[slot] ||
        '#ffffff'
    );
}

/**
 * Fills in every color slot and appearance entry a `theme` template does not
 * carry yet, defaulting to the colors and mode of the currently active vuetify
 * theme (pass `$vuetify.theme.current.colors` and `$vuetify.theme.current.dark`)
 * and, when `themeCodeEditor` is given, to the editor theme it is running with
 * (pass `getActiveCodeEditorTheme()`). Slots the template already holds are
 * left alone.
 */
export function hydrateThemeTemplate(template, themeColors, themeDark, themeCodeEditor) {
    const colors = { ...(template.colors || {}) };

    for (const group of THEME_COLOR_GROUPS) {
        const existing = colors[group.key] || {};
        const hydrated = { ...existing };
        for (const slot of group.slots) {
            if (!normalizeHexColor(hydrated[slot])) {
                hydrated[slot] = defaultThemeColor(group.key, slot, themeColors);
            }
        }
        colors[group.key] = hydrated;
    }

    const source = template.appearance || {};
    const appearance = { ...source };
    for (const [typ, flags] of Object.entries(THEME_APPEARANCE_TYPES)) {
        appearance[typ] = { italic: false, bold: false, ...flags, ...(source[typ] || {}) };
    }
    if (typeof appearance.backdrop_panel_opacity !== 'number') {
        appearance.backdrop_panel_opacity = 0.8;
    }
    if (typeof appearance.backdrop_text_shadow !== 'boolean') {
        appearance.backdrop_text_shadow = true;
    }

    if (typeof template.dark !== 'boolean') {
        template.dark = typeof themeDark === 'boolean' ? themeDark : true;
    }

    if (!isCodeEditorTheme(template.code_editor)) {
        template.code_editor = isCodeEditorTheme(themeCodeEditor)
            ? themeCodeEditor
            : DEFAULT_CODE_EDITOR_THEME;
    }

    template.colors = colors;
    template.appearance = appearance;
    return template;
}


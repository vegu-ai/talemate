import { labelForThemeSlot } from './templateMappings.js';

/**
 * The swatch slots shown per theme in the settings theme picker — the colors
 * that tell one theme from another at a glance.
 */
export const THEME_PICKER_SWATCH_SLOTS = [
    { group: 'surfaces', slot: 'background' },
    { group: 'surfaces', slot: 'surface' },
    { group: 'app', slot: 'primary' },
    { group: 'app', slot: 'secondary' },
];

// uid of the group the shipped themes live in — user groups get generated
// uuids, so this reliably identifies the shipped one; it leads the picker so
// the two themes every installation has are never buried under user groups
const SHIPPED_THEME_GROUP_UID = 'themes';

function byFavoriteThenName(a, b) {
    if (!!a.favorite !== !!b.favorite) {
        return a.favorite ? -1 : 1;
    }
    return (a.name || '').localeCompare(b.name || '');
}

function byShippedThenName(a, b) {
    const aShipped = a.uid === SHIPPED_THEME_GROUP_UID;
    const bShipped = b.uid === SHIPPED_THEME_GROUP_UID;
    if (aShipped !== bShipped) {
        return aShipped ? -1 : 1;
    }
    return (a.name || '').localeCompare(b.name || '');
}

/**
 * The theme picker's list: every `theme` template in the templates payload,
 * under its group. Groups without themes drop out, the shipped group leads,
 * favorites lead within a group. Each theme carries its `group__uid` id —
 * the form `config.appearance.theme` and template navigation both use.
 */
export function themePickerGroups(worldStateTemplates) {
    const groups = worldStateTemplates?.managed?.groups || [];
    return groups
        .map((group) => ({
            uid: group.uid,
            name: group.name || group.uid,
            themes: Object.values(group.templates || {})
                .filter((template) => template.template_type === 'theme')
                .map((template) => ({ ...template, id: `${group.uid}__${template.uid}` }))
                .sort(byFavoriteThenName),
        }))
        .filter((group) => group.themes.length > 0)
        .sort(byShippedThenName);
}

/**
 * The active theme's `group__uid` id, as `config.appearance.theme` stores it.
 */
export function themeIdFromConfig(config) {
    return config?.appearance?.theme || null;
}

export function isActiveTheme(theme, activeThemeId) {
    return !!activeThemeId && theme.id === activeThemeId;
}

/**
 * The `world_state_manager` message that makes a theme template the active
 * theme. Every sender goes through this — the settings page, the app bar
 * switcher and the theme editor — so a theme applies the same way from all
 * three.
 */
export function applyThemeTemplateMessage(theme) {
    const template = { ...theme };
    // `id` is the picker's own addition, not part of the template
    delete template.id;
    return {
        type: 'world_state_manager',
        action: 'apply_template',
        template,
        character_name: null,
        run_immediately: false,
    };
}

/**
 * Swatches for one theme row, with the slot label for the tooltip.
 */
export function themePickerSwatches(template) {
    const colors = template?.colors || {};
    return THEME_PICKER_SWATCH_SLOTS
        .map(({ group, slot }) => ({
            key: `${group}.${slot}`,
            label: labelForThemeSlot(slot),
            color: (colors[group] || {})[slot],
        }))
        .filter((swatch) => !!swatch.color);
}

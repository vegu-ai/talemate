import { THEME_APPEARANCE_MAP } from '@/utils/templateMappings';

/**
 * A copy of `sceneConfig` with the theme's styling put back and every per-type
 * color override dropped, so the colors resolve from the theme again.
 *
 * Mirrors the backend's `apply_theme_appearance`, which only ever copies a
 * field the target already carries, and leaves everything outside the mapped
 * styles - message assets, asset attachment - to the user.
 *
 * Without a theme to restore from there is nothing to restore to: the copy
 * comes back untouched, rather than dropping the colors for styling that then
 * never arrives.
 */
export function restoreAppearanceFromTheme(sceneConfig, themeAppearance) {
    const restored = JSON.parse(JSON.stringify(sceneConfig || {}));
    const appearance = themeAppearance || {};

    if (!Object.keys(appearance).length) {
        return restored;
    }

    for (const [themeKey, configKey] of Object.entries(THEME_APPEARANCE_MAP)) {
        const source = appearance[themeKey];
        const target = restored[configKey];
        const isStyle = target && typeof target === 'object';

        if (source && typeof source === 'object') {
            if (isStyle) {
                for (const field of Object.keys(source)) {
                    if (field in target) {
                        target[field] = source[field];
                    }
                }
            }
        } else if (source !== undefined && source !== null) {
            restored[configKey] = source;
        }

        if (isStyle && 'color' in target) {
            target.color = null;
        }
    }

    return restored;
}

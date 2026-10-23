import { PERSPECTIVE_PRESET_INFO, PERSPECTIVE_SAMPLE_NAME } from '@/constants/perspectivePresets';
import { hasOwnName } from '@/utils/nameKeyedMap';

const PERSPECTIVE_REQUEST = "Set up scene prose perspectives for me please, based on the prose information that exists so far. If there isn't enough information ask me what I am looking for, and make a simple suggestion that would please most readers.";

/**
 * The director cannot read the application config, so the presets the dropdown
 * offers travel with the request as one compact line.
 */
export function buildPerspectivePrompt(presets) {
    const configured = (presets || []).filter(preset => (preset || "").trim().length > 0);
    if (configured.length === 0) {
        return PERSPECTIVE_REQUEST;
    }
    return `${PERSPECTIVE_REQUEST}\n\nConfigured presets: ${configured.join("; ")}`;
}

/**
 * Display-only meaning and sample prose for a shipped preset, or null for one
 * the user renamed or added.
 */
export function perspectivePresetSubtitle(preset, formatTemplateString) {
    // a preset is free user text, so a name like `constructor` or `toString`
    // would otherwise resolve to a prototype member and pass the guard
    if (!hasOwnName(PERSPECTIVE_PRESET_INFO, preset)) return null;
    const info = PERSPECTIVE_PRESET_INFO[preset];
    return {
        meaning: info.meaning,
        sample: formatTemplateString
            ? formatTemplateString(info.sample, PERSPECTIVE_SAMPLE_NAME)
            : info.sample,
    };
}

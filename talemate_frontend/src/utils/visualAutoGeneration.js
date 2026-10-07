// Automatic image generation as the Visualizer scene tool shows and changes
// it. Every read is the scene's effective value (scene override first).
import { configOverrideActive, effectiveConfigValue } from '@/constants/sceneAgentSettings';

function readField(agent, actionKey, configKey) {
    return {
        value: effectiveConfigValue(agent?.actions, agent?.scene_overrides, `${actionKey}.config.${configKey}`),
        overridden: configOverrideActive(agent?.scene_overrides, actionKey, configKey),
    };
}

export function automaticGenerationState(visual) {
    if (!visual?.actions?._config?.config?.automatic_generation) return null;
    const field = readField(visual, '_config', 'automatic_generation');
    return { on: field.value === true, overridden: field.overridden };
}

// `actionKey` is a World State action with a generate_new / selection_frequency
// pair (avatars, backgrounds). Generation runs inside selection, so it is on
// only while selection runs too.
export function generationState(worldState, actionKey) {
    if (!worldState?.actions?.[actionKey]?.config?.generate_new) return null;
    const generateNew = readField(worldState, actionKey, 'generate_new');
    const frequency = readField(worldState, actionKey, 'selection_frequency');
    return {
        on: generateNew.value === true && Number(frequency.value) > 0,
        overridden: generateNew.overridden || frequency.overridden,
    };
}

// Switching generation off leaves the frequency alone, so picking between
// existing images keeps working.
export function generationValues(worldState, actionKey, on) {
    if (!on) return { config: { generate_new: false } };
    const config = { generate_new: true };
    const frequency = readField(worldState, actionKey, 'selection_frequency').value;
    if (!(Number(frequency) > 0)) config.selection_frequency = 1;
    return { config };
}

export function portraitsNeedGenerateVisuals(director) {
    return readField(director, 'character_management', 'generate_visuals').value === false;
}

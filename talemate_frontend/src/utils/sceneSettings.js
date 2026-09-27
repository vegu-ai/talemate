export const PERSPECTIVES_LOCKED_HINT = 'This scene has history. Character perspectives cannot be changed.';

export const PERSPECTIVES_OPEN_HINT = 'Choose before play. Adds Summarizer analyses and audience-specific context. Save the scene to keep this choice. Switching off discards stored character perspectives and cannot be undone after the next save.';

export function buildSceneSettingsPayload(sceneData, { knowledgeEligibility } = {}) {
    return {
        type: 'world_state_manager',
        action: 'update_scene_settings',
        ...(knowledgeEligibility ? { knowledge_eligibility: knowledgeEligibility } : {}),
        experimental: sceneData.experimental,
        immutable_save: sceneData.immutable_save,
        writing_style_template: sceneData.writing_style_template,
        agent_persona_templates: sceneData.agent_persona_templates || {},
        visual_style_template: sceneData.visual_style_template,
        restore_from: sceneData.restore_from,
    };
}

function templateOption(template) {
    return {
        value: `${template.group}__${template.uid}`,
        title: template.name,
        props: { subtitle: template.description },
    };
}

export function writingStyleOptions(templates) {
    return [
        { value: null, title: 'None', props: { subtitle: 'No writing style template selected.' } },
        ...Object.values(templates?.by_type?.writing_style || {}).map(templateOption),
    ];
}

export function visualStyleOptions(templates) {
    return [
        { value: null, title: 'Use Agent Default', props: { subtitle: 'Use the default art style from agent configuration.' } },
        ...Object.values(templates?.by_type?.visual_style || {})
            .filter((template) => template.visual_type === 'STYLE')
            .map(templateOption),
    ];
}

// Only the named setting: the server leaves every omitted field as it is.
export function sceneSettingPayload(setting, value) {
    return {
        type: 'world_state_manager',
        action: 'update_scene_settings',
        [setting]: value,
    };
}

export function perspectivesEnabled(sceneData) {
    return sceneData?.knowledge_eligibility === 'perception';
}

export function canChangePerspectives(sceneData) {
    return sceneData?.can_change_knowledge_eligibility === true;
}

// null when the scene has history: the server refuses the change, so the
// message is never sent.
export function perspectivesPayload(sceneData, enabled) {
    if (!canChangePerspectives(sceneData)) return null;
    return buildSceneSettingsPayload(sceneData, {
        knowledgeEligibility: enabled ? 'perception' : 'legacy',
    });
}

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

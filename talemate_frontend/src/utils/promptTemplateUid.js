export const SCENE_CATEGORY = 'scene';
export const SCENE_AGENT_FOLDER = 'scene (agent)';

export function templateFolder(agent) {
    if (agent === '') return SCENE_CATEGORY;
    if (agent === SCENE_CATEGORY) return SCENE_AGENT_FOLDER;
    return agent;
}

export function newTemplateUid(category, name, { sceneGroup = false } = {}) {
    const agent = sceneGroup && category === SCENE_CATEGORY ? '' : category;
    return `${agent}.${name}`;
}

export function newTemplateCategoryHint(category, { sceneGroup = false } = {}) {
    if (!sceneGroup || !category) {
        return 'Select the category this template belongs to';
    }
    if (category === SCENE_CATEGORY) {
        return 'Scene-level include, usable as a Direction instruction template';
    }
    return `Overrides the ${category} prompt template for this scene`;
}

export const VIS_TYPE_OPTIONS = [
  'CHARACTER_CARD',
  'CHARACTER_PORTRAIT',
  //'CHARACTER_SPRITE',
  'SCENE_CARD',
  'SCENE_BACKGROUND',
  'SCENE_ILLUSTRATION',
  //'ITEM_CARD',
  'UNSPECIFIED',
];

export const FORMAT_OPTIONS = ['LANDSCAPE', 'PORTRAIT', 'SQUARE'];

export function isCharacterVisType(visType) {
  return (visType || '').startsWith('CHARACTER_');
}

/**
 * Check if the visual agent is ready (either image_create or image_edit is available)
 * @param {Object} agentStatus - The agent status object
 * @returns {boolean} True if visual agent is ready for image generation
 */
export function isVisualAgentReady(agentStatus) {
  const visualAgent = agentStatus?.visual;
  if (!visualAgent || !visualAgent.meta) {
    return false;
  }
  return (
    visualAgent.meta?.image_create?.status === 'BackendStatusType.OK' ||
    visualAgent.meta?.image_edit?.status === 'BackendStatusType.OK'
  );
}

/**
 * Check if image editing is available
 * @param {Object} agentStatus - The agent status object
 * @returns {boolean} True if image editing is available
 */
export function isImageEditAvailable(agentStatus) {
  const visualAgent = agentStatus?.visual;
  if (!visualAgent || !visualAgent.meta) {
    return false;
  }
  const status = visualAgent.meta?.image_edit?.status;
  return status === 'BackendStatusType.OK';
}

/**
 * Check if image creation is available
 * @param {Object} agentStatus - The agent status object
 * @returns {boolean} True if image creation is available
 */
export function isImageCreateAvailable(agentStatus) {
  const visualAgent = agentStatus?.visual;
  if (!visualAgent || !visualAgent.meta) {
    return false;
  }
  const status = visualAgent.meta?.image_create?.status;
  return status === 'BackendStatusType.OK';
}



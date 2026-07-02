import { BACKEND_STATUS } from './backendStatus';

// Must match VIS_TYPE in src/talemate/agents/visual/schema.py
export const VIS_TYPE = Object.freeze({
  CHARACTER_CARD: 'CHARACTER_CARD',
  CHARACTER_PORTRAIT: 'CHARACTER_PORTRAIT',
  // CHARACTER_SPRITE: 'CHARACTER_SPRITE',
  SCENE_CARD: 'SCENE_CARD',
  SCENE_BACKGROUND: 'SCENE_BACKGROUND',
  SCENE_ILLUSTRATION: 'SCENE_ILLUSTRATION',
  OBJECT_ILLUSTRATION: 'OBJECT_ILLUSTRATION',
  UNSPECIFIED: 'UNSPECIFIED',
});

export const VIS_TYPE_OPTIONS = [
  VIS_TYPE.CHARACTER_CARD,
  VIS_TYPE.CHARACTER_PORTRAIT,
  VIS_TYPE.SCENE_CARD,
  VIS_TYPE.SCENE_BACKGROUND,
  VIS_TYPE.SCENE_ILLUSTRATION,
  VIS_TYPE.OBJECT_ILLUSTRATION,
  VIS_TYPE.UNSPECIFIED,
];

// Must match FORMAT_TYPE in src/talemate/agents/visual/schema.py
export const FORMAT_TYPE = Object.freeze({
  LANDSCAPE: 'LANDSCAPE',
  PORTRAIT: 'PORTRAIT',
  SQUARE: 'SQUARE',
});

export const FORMAT_OPTIONS = [
  FORMAT_TYPE.LANDSCAPE,
  FORMAT_TYPE.PORTRAIT,
  FORMAT_TYPE.SQUARE,
];

// Must match GEN_TYPE in src/talemate/agents/visual/schema.py
export const GEN_TYPE = Object.freeze({
  TEXT_TO_IMAGE: 'TEXT_TO_IMAGE',
  IMAGE_EDIT: 'IMAGE_EDIT',
  UPLOAD: 'UPLOAD',
});

export function isCharacterVisType(visType) {
  return (visType || '').startsWith('CHARACTER_');
}

export function isVisualAgentReady(agentStatus) {
  const visualAgent = agentStatus?.visual;
  if (!visualAgent || !visualAgent.meta) {
    return false;
  }
  return (
    visualAgent.meta?.image_create?.status === BACKEND_STATUS.OK ||
    visualAgent.meta?.image_edit?.status === BACKEND_STATUS.OK
  );
}

export function isImageEditAvailable(agentStatus) {
  const visualAgent = agentStatus?.visual;
  if (!visualAgent || !visualAgent.meta) {
    return false;
  }
  return visualAgent.meta?.image_edit?.status === BACKEND_STATUS.OK;
}

export function isImageCreateAvailable(agentStatus) {
  const visualAgent = agentStatus?.visual;
  if (!visualAgent || !visualAgent.meta) {
    return false;
  }
  return visualAgent.meta?.image_create?.status === BACKEND_STATUS.OK;
}

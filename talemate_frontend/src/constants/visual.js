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



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

// Must match FINALIZER_MODE in src/talemate/agents/visual/schema.py
export const FINALIZER_MODE = Object.freeze({
  EXACT: 'EXACT',
  FUZZY: 'FUZZY',
  REGEX: 'REGEX',
  AI: 'AI',
});

// Must match FINALIZER_TARGET in src/talemate/agents/visual/schema.py
export const FINALIZER_TARGET = Object.freeze({
  POSITIVE: 'POSITIVE',
  NEGATIVE: 'NEGATIVE',
  BOTH: 'BOTH',
});

function titleCase(value) {
  return value.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}

// Must match finalizer_table_columns() in src/talemate/agents/visual/finalize.py
export function finalizerTableColumns() {
  return [
    {
      name: 'enabled',
      type: 'bool',
      label: '',
      default_value: true,
      rail: true,
      disables_row: true,
    },
    {
      name: 'mode',
      type: 'text',
      label: 'Mode',
      default_value: FINALIZER_MODE.EXACT,
      span: 3,
      choices: [
        { label: 'Exact match', value: FINALIZER_MODE.EXACT },
        { label: 'Fuzzy match', value: FINALIZER_MODE.FUZZY },
        { label: 'Regex', value: FINALIZER_MODE.REGEX },
        { label: 'AI', value: FINALIZER_MODE.AI },
      ],
    },
    {
      name: 'target',
      type: 'text',
      label: 'Target',
      default_value: FINALIZER_TARGET.POSITIVE,
      span: 3,
      choices: [
        { label: 'Positive', value: FINALIZER_TARGET.POSITIVE },
        { label: 'Negative', value: FINALIZER_TARGET.NEGATIVE },
        { label: 'Both', value: FINALIZER_TARGET.BOTH },
      ],
    },
    {
      name: 'flags',
      type: 'flags',
      label: 'Flags',
      span: 3,
      choices: [
        { label: 'Case sensitive', value: 'case_sensitive' },
        { label: 'Dot all (regex)', value: 'dot_all' },
        { label: 'Multiline (regex)', value: 'multiline' },
      ],
      // fuzzy matching is always case insensitive and AI mode has no
      // flags — the stored value is ignored for those modes
      condition: {
        attribute: 'mode',
        value: [FINALIZER_MODE.EXACT, FINALIZER_MODE.REGEX],
      },
    },
    {
      name: 'vis_types',
      type: 'flags',
      label: 'Types',
      description: 'Visual types this action applies to. Empty applies to all.',
      span: 3,
      // take over the row when the flags column is hidden
      dynamic_span: {
        attribute: 'mode',
        spans: { [FINALIZER_MODE.FUZZY]: 6, [FINALIZER_MODE.AI]: 6 },
      },
      choices: VIS_TYPE_OPTIONS.map(visType => ({
        label: titleCase(visType),
        value: visType,
      })),
    },
    {
      name: 'match',
      type: 'blob',
      label: 'Match',
      description: 'Search string (exact, fuzzy) or pattern (regex).',
      span: 12,
      rows: 1,
      auto_grow: true,
      condition: {
        attribute: 'mode',
        value: [FINALIZER_MODE.EXACT, FINALIZER_MODE.FUZZY, FINALIZER_MODE.REGEX],
      },
    },
    {
      name: 'replace',
      type: 'blob',
      label: 'Replace',
      dynamic_label: {
        attribute: 'mode',
        labels: { [FINALIZER_MODE.AI]: 'Instruct' },
      },
      description: 'Replacement text, or the instruction for AI processing. An empty replacement removes the match.',
      span: 12,
      rows: 1,
      max_rows: 15,
      auto_grow: true,
    },
  ];
}

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

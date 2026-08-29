// Vuetify
import { createVuetify } from 'vuetify'
import colors from 'vuetify/util/colors'
import { vuetifySlotName } from '@/utils/templateMappings'

// The groups exist for the theme editor only — vuetify wants every slot at
// one level.
const THEME_COLOR_GROUPS = ['app', 'surfaces', 'messages', 'chats'];

const vuetify = createVuetify({
  theme : {
    defaultTheme: 'dark',
    themes: {
      dark: {
        colors: {
          // theme colors
          primary: colors.deepPurple.lighten2,
          secondary: colors.deepOrange.base,
          delete: colors.red.darken2,
          cancel: colors.blueGrey.lighten3,
          muted: colors.grey.base,
          mutedheader: colors.grey.lighten1,
          mutedbg: colors.grey.darken4,
          normal: colors.grey.base,
          unsaved: colors.amber.lighten2,
          favorite: colors.amber.accent2,
          highlight1: colors.indigo.lighten3,
          highlight2: colors.purple.lighten3,
          highlight3: colors.lightGreen.lighten3,
          highlight4: colors.red.lighten1,
          highlight5: colors.amber.lighten3,
          highlight6: colors.orange.lighten3,
          highlight7: colors.blue.lighten3,
          persona: colors.pink.lighten3,
          dirty: colors.orange.lighten2,

          inactive: colors.red.lighten2,

          // vuetify's stock dark values, pinned so a future vuetify release
          // cannot move them out from under Talemate Dark
          success: '#4CAF50',
          info: '#2196F3',
          warning: '#FB8C00',
          error: '#CF6679',

          // node module tiles in the node editor library
          module_selected: colors.deepPurple.lighten1,
          module_locked_selected: colors.blueGrey.lighten1,

          // messages
          narrator: '#A180AE',
          actor: colors.deepPurple.lighten3,
          character: colors.shades.white,
          director: colors.deepOrange.base,
          time: colors.amber.lighten4,
          context_investigation: colors.orange.lighten4,
          information: '#BA8574',
          quotes: colors.shades.white,
          parentheses: '#DB9DC2',
          brackets: '#DC5D5D',
          emphasis: colors.deepPurple.lighten3,
          entities: colors.amber.lighten3,
          play_audio: colors.yellow.darken2,
          border: colors.grey.darken3,
          defaultBadge: colors.deepOrange.darken2,


          // director chat
          dchat_msg_director: colors.deepOrange.lighten2,
          dchat_msg_action_result: colors.deepOrange.lighten4,
          dchat_msg_compaction: colors.grey.darken2,

          // help chat
          hchat_msg_help: colors.blueGrey.lighten2,
          hchat_msg_doc_result: colors.blue.lighten2,
          
          // html colors
          cornflowerblue: "#6495ED",
        }
      }
    }
  }
})

// vuetify merges its stock light/dark `variables` (border color, emphasis
// opacities, code/kbd colors) into a theme when the instance is created and
// never again, so a theme that flips to light has to be handed the light set
// or it keeps dark's white borders.
const STOCK_THEME_VARIABLES = {
  light: { ...vuetify.theme.themes.value.light.variables },
  dark: { ...vuetify.theme.themes.value.dark.variables },
};

// vuetify dims medium emphasis text harder on light (0.60) than on dark (0.70).
// several wrappers - `.v-messages`, `.v-card-subtitle`, disabled list items -
// dim by opacity of their own before any color is chosen, and the two multiply,
// which put muted text on a light theme under AA. dark's value is readable
// under the same stacking, so both modes use it.
const THEME_VARIABLE_OVERRIDES = {
  light: { 'medium-emphasis-opacity': 0.70 },
  dark: {},
};

export function stockThemeVariables(dark) {
  const mode = dark ? 'dark' : 'light';
  return { ...STOCK_THEME_VARIABLES[mode], ...THEME_VARIABLE_OVERRIDES[mode] };
}

export function flattenThemeColors(resolvedTheme) {
  const colors = resolvedTheme?.colors;
  if (!colors || typeof colors !== 'object') {
    return null;
  }

  const flat = {};
  for (const group of THEME_COLOR_GROUPS) {
    const groupColors = colors[group];
    if (!groupColors || typeof groupColors !== 'object') {
      continue;
    }
    for (const [slot, value] of Object.entries(groupColors)) {
      if (typeof value === 'string' && value) {
        flat[vuetifySlotName(group, slot)] = value;
      }
    }
  }

  // `character` has no theme slot of its own, so it tracks the actor color
  // instead of drifting away from it.
  if (flat.actor) {
    flat.character = flat.actor;
  }

  return Object.keys(flat).length ? flat : null;
}

export function applyTheme(resolvedTheme, themeInstance = vuetify.theme) {
  const flat = flattenThemeColors(resolvedTheme);
  const definition = themeInstance?.themes?.value?.dark;
  if (!flat || !definition?.colors) {
    return null;
  }
  // Mutating the reactive theme definition in place keeps slots the theme
  // does not carry (cornflowerblue) and republishes the CSS variables.
  Object.assign(definition.colors, flat);

  if (typeof resolvedTheme.dark === 'boolean' && resolvedTheme.dark !== definition.dark) {
    definition.dark = resolvedTheme.dark;
    Object.assign(definition.variables, stockThemeVariables(resolvedTheme.dark));
  }
  return flat;
}

export default vuetify

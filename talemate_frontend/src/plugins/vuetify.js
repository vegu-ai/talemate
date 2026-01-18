// Styles
import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'

// Vuetify
import { createVuetify } from 'vuetify'
import colors from 'vuetify/util/colors'

export default createVuetify({
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
          instructions: colors.orange.lighten4,

          enabled: colors.green.lighten2,
          disabled: colors.red.lighten2,

          // node editor
          nodeeditorbg: colors.grey.darken2,
          core_node: colors.blueGrey.lighten1,
          core_node_selected: colors.blueGrey.lighten1,
          template_node: colors.brown.lighten2,
          template_node_selected: colors.brown.lighten2,
          scene_node: colors.deepPurple.lighten2,
          scene_node_selected: colors.deepPurple.lighten1,

          // messages
          narrator: colors.deepPurple.lighten3,
          character: colors.shades.white,
          director: colors.deepOrange.base,
          time: colors.amber.lighten4,
          context_investigation: colors.orange.lighten4,
          play_audio: colors.yellow.darken2,
          avatar_border: colors.grey.darken3,
          defaultBadge: colors.deepOrange.darken2,


          // director chat
          dchat_msg_director: colors.deepOrange.lighten2,
          dchat_msg_user: colors.deepPurple.lighten3,
          dchat_msg_action_result: colors.deepOrange.lighten4,
          dchat_msg_loading: colors.deepOrange.lighten1,
          dchat_msg_compaction: colors.grey.darken2,
          dchat_msg_code: colors.deepOrange.lighten4,
          
          // html colors
          cornflowerblue: "#6495ED",
        }
      }
    }
  }
})

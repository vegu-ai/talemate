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
          muted: colors.grey.darken1,
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
          dirty: colors.orange.lighten2,

          // messages
          narrator: colors.deepPurple.lighten3,
          character: colors.shades.white,
          director: colors.deepOrange.base,
          time: colors.deepPurple.lighten3,
          context_investigation: colors.blueGrey.base,

          // html colors
          cornflowerblue: "#6495ED",
        }
      }
    }
  }
})

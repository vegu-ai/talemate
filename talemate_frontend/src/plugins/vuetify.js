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
          primary: colors.deepPurple.lighten2,
          secondary: colors.deepOrange.base,
          delete: colors.red.darken2,
          cancel: colors.blueGrey.lighten3,
        }
      }
    }
  }
})

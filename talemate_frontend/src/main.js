// Load Vuetify's layer order before component styles; this import order is load-bearing.
import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import './assets/vuetify-reset.css'

import { createApp } from 'vue'
import App from './App.vue'
import vuetify from './plugins/vuetify'
import { loadFonts } from './plugins/webfontloader'

loadFonts()

createApp(App)
  .use(vuetify)
  .mount('#app')

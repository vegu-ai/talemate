const { defineConfig } = require('@vue/cli-service')

const ALLOWED_HOSTS = ((process.env.ALLOWED_HOSTS || "all") !== "all" ? process.env.ALLOWED_HOSTS.split(",") : "all")
const VUE_APP_TALEMATE_BACKEND_WEBSOCKET_URL = process.env.VUE_APP_TALEMATE_BACKEND_WEBSOCKET_URL || null

console.log("NODE_ENV", process.env.NODE_ENV)
console.log("ALLOWED_HOSTS", ALLOWED_HOSTS)
console.log("VUE_APP_TALEMATE_BACKEND_WEBSOCKET_URL", VUE_APP_TALEMATE_BACKEND_WEBSOCKET_URL)

module.exports = defineConfig({
  transpileDependencies: true,

  pluginOptions: {
    vuetify: {
			// https://github.com/vuetifyjs/vuetify-loader/tree/next/packages/vuetify-loader
		}
  },

  devServer: {
    allowedHosts: ALLOWED_HOSTS,
    client: {
      overlay: {
        warnings: false,
        errors: false,
      },

      // or
      overlay: false,
    }
  }
})

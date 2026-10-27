/**
 * plugins/webfontloader.js
 *
 * webfontloader documentation: https://github.com/typekit/webfontloader
 */

export async function loadFonts () {
  const webFontLoader = await import(/* webpackChunkName: "webfontloader" */'webfontloader')

  webFontLoader.load({
    google: {
      // the families join into one URL, so display=swap rides on the last
      families: ['Lora:500', 'Roboto:100,300,400,500,700,900&display=swap'],
    },
  })
}

/**
 * Inserts a newline at the current cursor position in a Vuetify v-textarea.
 *
 * @param {object} textareaRef - The Vue ref to the Vuetify v-textarea component
 * @param {string} text - The current text value
 * @param {function} setText - Callback to update the text value
 */
export function insertNewlineAtCursor(textareaRef, text, setText) {
    const el = textareaRef.$el.querySelector('textarea');
    const start = el.selectionStart;
    const end = el.selectionEnd;
    setText(text.substring(0, start) + "\n" + text.substring(end));
    // Restore cursor position after Vue re-renders
    const vm = textareaRef.$parent || textareaRef;
    vm.$nextTick(() => {
        el.selectionStart = el.selectionEnd = start + 1;
    });
}

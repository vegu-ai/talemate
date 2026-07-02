<template>
  <div class="position-relative scene-message-input-root">
    <v-textarea
      v-model="inputValue"
      :label="inputHint"
      rows="1"
      auto-grow
      outlined
      ref="textarea"
      @keydown.enter.prevent="onEnter"
      @keydown.ctrl.up.prevent="onHistoryUp"
      @keydown.meta.up.prevent="onHistoryUp"
      @keydown.ctrl.down.prevent="onHistoryDown"
      @keydown.meta.down.prevent="onHistoryDown"
      @keydown.tab.prevent="cycleActAs"
      :hint="inputLongHint"
      :disabled="disabled"
      :loading="autocompleteField?.state.autocompleting || false"
      :prepend-inner-icon="inputIcon"
      :color="inputColor">
      <template v-slot:prepend v-if="sceneActive && sceneEnvironment !== 'creative'">
        <v-btn @click="triggerAutocomplete" color="primary" icon variant="tonal" :disabled="!inputValue || disabled">
          <v-icon>mdi-auto-fix</v-icon>
        </v-btn>
      </template>
      <template v-slot:append>
        <v-btn @click="onEnter" color="primary" icon variant="tonal" :disabled="disabled">
          <v-icon v-if="inputValue">mdi-send</v-icon>
          <v-icon v-else>mdi-skip-next</v-icon>
        </v-btn>
      </template>
    </v-textarea>
    <AutocompleteRedoChip
      :applied="autocompleteField?.state.applied || false"
      :disabled="disabled"
      @redo="autocompleteField.redo()"
      @undo="autocompleteField.undo()" />
  </div>
</template>

<style scoped>
/* Override the chip's default right offset to clear the v-textarea's append
   slot (send button); the chip itself owns top / position / z-index. */
.scene-message-input-root {
  --autocomplete-redo-chip-right: 64px;
}
</style>

<script>
import { isPrimaryModifier, primaryModifierLabel } from '@/utils/keyboardModifiers';
import AutocompleteRedoChip from './AutocompleteRedoChip.vue';
import { createAutocompleteField } from '@/utils/autocompleteField';

const INPUT_HISTORY_MAX = 10;

// Prefix-mode table: when the user's message starts with one of these
// sequences, the input surfaces a mode-specific label / icon / color so they
// know they've triggered a non-dialogue path before hitting Enter. The
// backend is the one that actually interprets the prefix on send; this is
// pure UX affordance.
//
// Longest-first ordering matters — '##' must be checked before '#'.
const PREFIXES = [
  {
    match: '##',
    mode: 'direct-yield',
    icon: 'mdi-pound',
    color: 'director',
    label: 'Talk to Director (keep turn)',
    longHint: 'Send instruction to the director, then yield the turn back to you.',
    requiresDirection: true,
  },
  {
    match: '#',
    mode: 'direct',
    icon: 'mdi-pound',
    color: 'director',
    label: 'Talk to Director (yield turn)',
    longHint: 'Send instruction to the director. The scene continues after. Use ## to keep your turn.',
    requiresDirection: true,
  },
  {
    match: '!',
    mode: 'command',
    icon: 'mdi-powershell',
    color: 'warning',
    label: 'Command',
    longHint: 'Executes a command on the scene engine.',
  },
  {
    match: '@',
    mode: 'action',
    icon: 'mdi-at',
    // color / label / longHint are resolved dynamically based on actAs
  },
];

export default {
  name: 'SceneMessageInput',
  components: { AutocompleteRedoChip },
  inject: ['autocompleteRequest'],
  props: {
    // The textarea's text, bound via v-model on the parent.
    modelValue: { type: String, default: '' },
    // Who the player is speaking as. null = the player character, '$narrator' =
    // the narrator, any other string = a named character. Two-way bound via
    // v-model:act-as; Tab cycling mutates it through update:actAs.
    actAs: { type: String, default: null },
    // App-level activity flags. The component merges them into a single
    // `disabled` computed and doesn't react to them individually.
    busy: { type: Boolean, default: false },
    ready: { type: Boolean, default: false },
    uxInteractionActive: { type: Boolean, default: false },
    // Parent-owned "we've already sent, waiting on the server" gate. The
    // parent flips this to true right after our `send` / `autocomplete-start`
    // and back to false when the server responds. Prevents double-sends.
    inputDisabled: { type: Boolean, default: false },
    // Parent-owned "server is asking the user for input right now" state.
    // Drives all hint/icon/color branches — when false, the input is an idle
    // skip-turn control (mdi-cancel) and has no label or color.
    waitingForInput: { type: Boolean, default: false },
    // Payload of the current request_input message from the server. `.reason`
    // === 'talk' means dialogue prompt (player/character/narrator line);
    // anything else means a generic prompt and `.message` is shown as label.
    inputRequestInfo: { type: Object, default: null },
    // A scene is loaded. Gates the autocomplete prepend button visibility.
    sceneActive: { type: Boolean, default: false },
    // 'scene' vs 'creative' — autocomplete prepend is hidden in creative mode.
    sceneEnvironment: { type: String, default: 'scene' },
    // Map of character name -> color string; used to tint the input based on
    // who the user is currently speaking as.
    characterColors: { type: Object, default: () => ({}) },
    // Fallback for the hint label when actAs is null (player talks as self).
    playerCharacterName: { type: String, default: null },
    // Needed by cycleActAs (Tab) — the order determines cycle order.
    activeCharacters: { type: Array, default: () => [] },
    // True when director scene direction is usable — either the agent has it
    // enabled, or the current scene forces it on. Gates whether the `#`/`##`
    // prefixes surface as interactive mode affordances.
    directionAvailable: { type: Boolean, default: false },
  },
  emits: [
    'update:modelValue',
    'update:actAs',
    'send',
    'autocomplete-start',
    'autocomplete-end',
  ],
  data() {
    return {
      inputHistory: [],
      historyIndex: 0,
      draftBeforeHistoryBrowse: '',
      autocompleteField: null,
    };
  },
  created() {
    this.autocompleteField = createAutocompleteField({
      autocompleteRequest: this.autocompleteRequest,
      getValue: () => this.inputValue,
      setValue: (v) => { this.inputValue = v; },
      buildParams: () => {
        let context = 'dialogue:player';
        if (this.actAs) {
          context = this.actAs === '$narrator' ? 'narrative:' : `dialogue:${this.actAs}`;
        }
        return { partial: this.inputValue, context, character: this.actAs };
      },
      onStart: () => this.$emit('autocomplete-start'),
      onEnd: () => this.$emit('autocomplete-end'),
    });
  },
  watch: {
    modelValue() {
      this.autocompleteField?.onValueChange();
    },
  },
  computed: {
    // v-model indirection: read from the prop, write through the emit so the
    // parent stays the source of truth for the textarea's value.
    inputValue: {
      get() { return this.modelValue; },
      set(v) { this.$emit('update:modelValue', v); },
    },
    // Single disabled signal for the textarea and both buttons. Combines
    // app-wide gating (busy/ready/uxInteractionActive) with the parent's
    // explicit inputDisabled flag.
    disabled() {
      return this.busy || !this.ready || this.uxInteractionActive || this.inputDisabled;
    },
    // True only when the server is actively soliciting a dialogue line.
    // Autocomplete is only meaningful in that context.
    isWaitingForDialogInput() {
      return this.waitingForInput && this.inputRequestInfo && this.inputRequestInfo.reason === 'talk';
    },
    // Active prefix mode, derived from the textarea's current content. Only
    // surfaces while the server is actively soliciting a dialogue line —
    // outside that context prefixes have no meaning. Returns null when no
    // prefix matches or when a prefix is gated off (e.g. '#' with no
    // director availability).
    inputMode() {
      if (!this.isWaitingForDialogInput) return null;
      if (!this.inputValue) return null;

      for (const p of PREFIXES) {
        if (!this.inputValue.startsWith(p.match)) continue;

        // Prefix matches but the mode is unavailable — surface a disabled
        // affordance so the user knows their prefix won't do what they think.
        if (p.requiresDirection && !this.directionAvailable) {
          return {
            ...p,
            label: `${p.label} — unavailable`,
            color: 'muted',
            longHint: 'Scene direction is disabled. Enable it in the director agent settings or the scene direction config.',
          };
        }

        if (p.mode === 'action') {
          return {
            ...p,
            label: `${this.actAsDisplayName} acts`,
            color: this.actAsColor || 'primary',
            longHint: `Generate action or dialogue for ${this.actAsDisplayName}. Text after '@' is the directive.`,
          };
        }
        return p;
      }
      return null;
    },
    // Display name for whoever we're currently speaking/acting as. Resolves
    // '$narrator' → 'Narrator', null → the player character name.
    actAsDisplayName() {
      if (this.actAs === '$narrator') return 'Narrator';
      return this.actAs || this.playerCharacterName || 'Player';
    },
    // Themed color for the current actAs, if one is configured. Falls back
    // to null so callers can pick their own default.
    actAsColor() {
      if (this.actAs === '$narrator') return 'narrator';
      const name = this.actAs || this.playerCharacterName;
      return name ? this.characterColors?.[name] : null;
    },
    // The floating textarea label — prefix-mode label if one is active, else
    // the speaker name for dialogue prompts, the server's message text for
    // generic prompts, empty when idle.
    inputHint() {
      if (this.inputMode) return this.inputMode.label;
      if (this.waitingForInput) {
        if (this.inputRequestInfo?.reason === 'talk') {
          return `${this.actAsDisplayName}:`;
        }
        return this.inputRequestInfo?.message;
      }
      return '';
    },
    // Keyboard-hint line shown below the textarea. Prefix-mode replaces it
    // with a concrete description of what the prefix does; otherwise the
    // standard dialogue keyboard shortcuts.
    inputLongHint() {
      if (this.inputMode) return this.inputMode.longHint;
      if (this.waitingForInput && this.inputRequestInfo?.reason === 'talk') {
        return `${primaryModifierLabel}+Enter to autocomplete, Shift+Enter for newline, ${primaryModifierLabel}+Up/Down for history, Tab to act as another character. Start messages with '@' to do an action. (e.g., '@look at the door')`;
      }
      return '';
    },
    // Prepend icon: prefix-mode icon when active, warning glyph for generic
    // prompts, speaker-type glyph for dialogue prompts, mdi-cancel when idle
    // (signalling "skip turn" behavior).
    inputIcon() {
      if (this.inputMode) return this.inputMode.icon;
      if (this.waitingForInput) {
        if (this.inputRequestInfo?.reason !== 'talk') {
          return 'mdi-information-outline';
        }
        if (this.actAs === '$narrator') return 'mdi-script-text-outline';
        return 'mdi-comment-outline';
      }
      return 'mdi-cancel';
    },
    // Textarea color: prefix-mode color when active, warning for generic
    // prompts, per-character color for dialogue prompts when configured,
    // primary as fallback, null (inherits default) when idle.
    inputColor() {
      if (this.inputMode) return this.inputMode.color;
      if (!this.waitingForInput) return null;
      if (this.inputRequestInfo?.reason !== 'talk') return 'warning';
      return this.actAsColor || 'primary';
    },
  },
  methods: {
    focus() {
      this.$refs.textarea?.focus();
    },
    scrollIntoView(options) {
      this.$el?.scrollIntoView?.(options);
    },
    triggerAutocomplete() {
      if (!this.isWaitingForDialogInput) return;
      // `this` is passed as the focus target — the session-layer autocompleteRequest
      // calls .focus() on it after the suggestion arrives, which hits our
      // exposed focus() method and delegates to the inner textarea.
      this.autocompleteField.request(this, 100);
    },
    onEnter(event) {
      if (event && isPrimaryModifier(event) && event.key === 'Enter') {
        return this.triggerAutocomplete();
      }
      if (this.uxInteractionActive) return;
      if (event && event.shiftKey && event.key === 'Enter') {
        const textarea = this.$refs.textarea.$el.querySelector('textarea');
        const cursorPos = textarea.selectionStart;
        this.inputValue = this.inputValue.slice(0, cursorPos) + '\n' + this.inputValue.slice(cursorPos);
        this.$nextTick(() => {
          textarea.selectionStart = textarea.selectionEnd = cursorPos + 1;
        });
        return;
      }
      if (!this.inputDisabled) {
        const sentText = this.inputValue;
        this.$emit('send', { text: sentText, actAs: this.actAs });
        const trimmed = (sentText || '').trim();
        if (trimmed.length > 0) {
          this.inputHistory.unshift(sentText);
          if (this.inputHistory.length > INPUT_HISTORY_MAX) {
            this.inputHistory.length = INPUT_HISTORY_MAX;
          }
        }
        this.draftBeforeHistoryBrowse = '';
        this.historyIndex = 0;
        this.inputValue = '';
      }
    },
    onHistoryUp() {
      if (!this.inputHistory || this.inputHistory.length === 0) return;
      const maxUp = this.inputHistory.length;
      if (this.historyIndex <= -maxUp) return;
      if (this.historyIndex === 0) {
        this.draftBeforeHistoryBrowse = this.inputValue;
      }
      this.historyIndex -= 1;
      const historyPos = -this.historyIndex - 1;
      this.inputValue = this.inputHistory[historyPos] ?? '';
      this.moveCursorToEnd();
    },
    onHistoryDown() {
      if (this.historyIndex === 0) return;
      this.historyIndex += 1;
      if (this.historyIndex === 0) {
        this.inputValue = this.draftBeforeHistoryBrowse || '';
        this.moveCursorToEnd();
        return;
      }
      const historyPos = -this.historyIndex - 1;
      if (historyPos < 0 || historyPos >= this.inputHistory.length) {
        this.historyIndex = 0;
        return;
      }
      this.inputValue = this.inputHistory[historyPos] ?? '';
      this.moveCursorToEnd();
    },
    moveCursorToEnd() {
      this.$nextTick(() => {
        const textarea = this.$refs.textarea?.$el?.querySelector('textarea');
        if (textarea) {
          const len = this.inputValue.length;
          textarea.selectionStart = textarea.selectionEnd = len;
        }
      });
    },
    cycleActAs() {
      const playerCharacterName = this.playerCharacterName;

      if (!this.activeCharacters || this.activeCharacters.length === 0) {
        this.$emit('update:actAs', '$narrator');
        return;
      }

      if (this.actAs === '$narrator') {
        this.$emit('update:actAs', null);
        return;
      }

      let selectedCharacter = null;
      let foundActAs = false;

      for (const characterName of this.activeCharacters) {
        if (this.actAs === '$narrator') {
          selectedCharacter = characterName;
          break;
        }
        if (this.actAs === null && characterName !== playerCharacterName) {
          selectedCharacter = characterName;
          break;
        }
        if (foundActAs) {
          selectedCharacter = characterName;
          break;
        } else if (characterName === this.actAs) {
          foundActAs = true;
        }
      }

      if (selectedCharacter === null || selectedCharacter === playerCharacterName) {
        this.$emit('update:actAs', '$narrator');
      } else {
        this.$emit('update:actAs', selectedCharacter);
      }
    },
  },
};
</script>

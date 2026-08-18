// The theme editor's live preview: a dynamically registered vuetify theme that
// renders the template being edited (not the applied theme), plus the element
// map that makes every colour slot clickable from a real UI element.

import vuetify, { flattenThemeColors, stockThemeVariables } from '@/plugins/vuetify';
import { THEME_COLOR_GROUPS, labelForThemeSlot } from './templateMappings';

export const PREVIEW_THEME_NAME = 'template-preview';

/**
 * Registers or updates the preview theme from a theme template's colors and
 * mode. Vuetify generates the scoped `.v-theme--template-preview` variables —
 * including the auto `on-*` contrast colors — so a `v-theme-provider` with
 * this name renders the edited theme without touching the applied one.
 */
export function updatePreviewTheme(template) {
    const flat = flattenThemeColors(template);
    if (!flat) {
        return false;
    }
    const dark = template.dark !== false;
    vuetify.theme.themes.value[PREVIEW_THEME_NAME] = {
        dark,
        colors: flat,
        variables: stockThemeVariables(dark),
    };
    return true;
}

export function removePreviewTheme() {
    delete vuetify.theme.themes.value[PREVIEW_THEME_NAME];
}

function slotGroup(slot) {
    const group = THEME_COLOR_GROUPS.find(g => g.slots.includes(slot));
    return group ? group.key : null;
}

/**
 * Registry of the preview's clickable elements and the colour slot each edits,
 * keyed by element id. The component places elements by id from its own layout
 * lists; the unit test pins that all 51 slots of THEME_COLOR_GROUPS have an
 * element and that every element names a real slot.
 *
 * `onColorDerived` marks elements whose text vuetify paints with the automatic
 * `on-*` contrast colour rather than a slot.
 */
export const THEME_PREVIEW_ELEMENTS = {
    'app.primary': { group: 'app', slot: 'primary', label: 'Primary', onColorDerived: true },
    'app.secondary': { group: 'app', slot: 'secondary', label: 'Secondary', onColorDerived: true },
    'app.delete': { group: 'app', slot: 'delete', label: 'Delete', onColorDerived: true },
    'app.cancel': { group: 'app', slot: 'cancel', label: 'Cancel', onColorDerived: true },
    'app.muted': { group: 'app', slot: 'muted', label: 'Muted text steps back from the ordinary text.' },
    'app.mutedheader': { group: 'app', slot: 'mutedheader', label: 'Muted header' },
    'app.mutedbg': { group: 'app', slot: 'mutedbg', label: 'Toolbar band' },
    'app.normal': { group: 'app', slot: 'normal', label: 'The quick brown fox jumps over the lazy dog.' },
    'app.unsaved': { group: 'app', slot: 'unsaved', icon: 'mdi-content-save-alert-outline', label: 'Unsaved' },
    'app.dirty': { group: 'app', slot: 'dirty', icon: 'mdi-circle-edit-outline', label: 'Edited' },
    'app.favorite': { group: 'app', slot: 'favorite', icon: 'mdi-star', label: 'Favorite' },
    'app.persona': { group: 'app', slot: 'persona', icon: 'mdi-drama-masks', label: 'Persona' },
    'app.highlight1': { group: 'app', slot: 'highlight1', icon: 'mdi-badge-account', label: 'Attribute' },
    'app.highlight2': { group: 'app', slot: 'highlight2', icon: 'mdi-account-details', label: 'Detail' },
    'app.highlight3': { group: 'app', slot: 'highlight3', icon: 'mdi-image-auto-adjust', label: 'Tracking' },
    'app.highlight4': { group: 'app', slot: 'highlight4', icon: 'mdi-chili-mild', label: 'Spices' },
    'app.highlight5': { group: 'app', slot: 'highlight5', icon: 'mdi-script-text', label: 'Style' },
    'app.highlight6': { group: 'app', slot: 'highlight6', icon: 'mdi-movie-open', label: 'Scene type' },
    'app.highlight7': { group: 'app', slot: 'highlight7', icon: 'mdi-lightning-bolt', label: 'Shortcut' },
    'app.inactive': { group: 'app', slot: 'inactive', icon: 'mdi-toggle-switch-off-outline', label: 'A switched-off setting' },
    'app.module_selected': { group: 'app', slot: 'module_selected', icon: 'mdi-cube-scan', label: 'Module' },
    'app.module_locked_selected': { group: 'app', slot: 'module_locked_selected', icon: 'mdi-lock', label: 'Locked' },
    'app.success': { group: 'app', slot: 'success', icon: 'mdi-check-circle-outline', label: 'It worked.' },
    'app.info': { group: 'app', slot: 'info', icon: 'mdi-information-outline', label: 'For your information.' },
    'app.warning': { group: 'app', slot: 'warning', icon: 'mdi-alert-outline', label: 'Careful with that.' },
    'app.error': { group: 'app', slot: 'error', icon: 'mdi-alert-octagon-outline', label: 'That went wrong.' },

    'surfaces.background': { group: 'surfaces', slot: 'background', label: 'Background' },
    'surfaces.surface': { group: 'surfaces', slot: 'surface', label: 'Surface' },
    'surfaces.surface_bright': { group: 'surfaces', slot: 'surface_bright', label: 'Surface bright' },
    'surfaces.surface_light': { group: 'surfaces', slot: 'surface_light', label: 'Surface light' },
    'surfaces.surface_variant': { group: 'surfaces', slot: 'surface_variant', label: 'Surface variant' },
    'surfaces.on_surface_variant': { group: 'surfaces', slot: 'on_surface_variant', label: 'Text on the variant surface' },

    'messages.narrator': { group: 'messages', slot: 'narrator', icon: 'mdi-script-text-outline' },
    'messages.actor': { group: 'messages', slot: 'actor', icon: 'mdi-chat-outline' },
    'messages.director': { group: 'messages', slot: 'director', icon: 'mdi-bullhorn-outline' },
    'messages.time': { group: 'messages', slot: 'time', icon: 'mdi-clock-outline' },
    'messages.context_investigation': { group: 'messages', slot: 'context_investigation', icon: 'mdi-text-search' },
    'messages.information': { group: 'messages', slot: 'information', icon: 'mdi-information-outline' },
    'messages.quotes': { group: 'messages', slot: 'quotes' },
    'messages.parentheses': { group: 'messages', slot: 'parentheses' },
    'messages.brackets': { group: 'messages', slot: 'brackets' },
    'messages.emphasis': { group: 'messages', slot: 'emphasis' },
    'messages.entities': { group: 'messages', slot: 'entities' },
    'messages.play_audio': { group: 'messages', slot: 'play_audio', icon: 'mdi-play-circle-outline', label: 'Played back' },
    'messages.border': { group: 'messages', slot: 'border', icon: 'mdi-account' },
    'messages.defaultBadge': { group: 'messages', slot: 'defaultBadge', label: 'Current' },

    'chats.dchat_msg_director': { group: 'chats', slot: 'dchat_msg_director', label: 'Director: let us pick up the pace.' },
    'chats.dchat_msg_action_result': { group: 'chats', slot: 'dchat_msg_action_result', label: 'Action result: the scene moved on.' },
    'chats.dchat_msg_compaction': { group: 'chats', slot: 'dchat_msg_compaction', label: 'The chat so far, compacted.' },
    'chats.hchat_msg_help': { group: 'chats', slot: 'hchat_msg_help', label: 'Help: here is how that works.' },
    'chats.hchat_msg_doc_result': { group: 'chats', slot: 'hchat_msg_doc_result', label: 'From the docs: themes hold colours.' },
};

/**
 * Elements that paint through a derivation rather than their own slot. Clicking
 * one shows the note and offers the source slot's picker in place
 * (`derivedFrom`); a null `derivedFrom` means the mode decides, not a slot.
 */
export const THEME_PREVIEW_DERIVED_ELEMENTS = {
    'chats.dchat_msg_user': {
        note: 'Your own director chat messages take the Actor colour from Messages.',
        derivedFrom: { group: 'messages', slot: 'actor' },
    },
    'chats.hchat_msg_user': {
        note: 'Your own help chat messages take the Actor colour from Messages.',
        derivedFrom: { group: 'messages', slot: 'actor' },
    },
    'surfaces.on_surface': {
        note: 'Body text on cards is derived from Surface for contrast.',
        derivedFrom: { group: 'surfaces', slot: 'surface' },
    },
    'surfaces.divider': {
        note: 'Dividers and outlines are drawn from the theme mode (Light / Dark), not a colour slot.',
        derivedFrom: null,
    },
};

// Markup with its `override_color` off paints in the colour of the message it
// appears in, so the derivation offers that message type's slot - unless the
// markup was picked outside a message, where there is no one type to offer.
export function inheritedMarkupDerivation(markupSlot, messageType) {
    return {
        note: `${labelForThemeSlot(markupSlot)} takes the colour of the message it appears in, because Own color is off.`,
        derivedFrom: messageType ? { group: 'messages', slot: messageType } : null,
    };
}

export function isValidPreviewSlot(groupKey, slot) {
    return slotGroup(slot) === groupKey;
}

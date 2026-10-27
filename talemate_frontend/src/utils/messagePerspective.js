import { perspectivesEnabled } from '@/utils/sceneSettings';

// rows the frontend puts in the list by itself; the server knows nothing of
// them, so no view ever arrives for one. The server reports on every other row.
const INTERFACE_ROW_TYPES = ['system', 'status', 'request_input', 'player_choice', 'ux'];

const INTERFACE_ROW_VIEW = { status: 'unsupported', text: null, editable: false, reason: 'Only story messages have perspectives.' };

// the server sends the reason of a state it refuses to edit (view.reason)
const EMPTY_REASONS = {
    omitted: (name) => `${name} noticed nothing of this message.`,
    pending: () => 'The analysis of this message did not run yet.',
    failed: () => 'The analysis of this message failed.',
    unavailable: (name) => `${name} has no perspective of this message yet.`,
    not_present: (name) => `${name} was not present for the intro.`,
};

export function perspectiveChipLabel(character) {
    return character ? `View Perspective: ${character}` : 'View Perspective';
}

export function perspectiveHeaderLabel(character) {
    return `${character}'s Perspective`;
}

export function perspectiveCharacterValid(character, activeCharacters, sceneData) {
    return !!character && perspectivesEnabled(sceneData) && (activeCharacters || []).includes(character);
}

export function perspectiveEmptyReason(view, character) {
    const reason = view.reason || EMPTY_REASONS[view.status]?.(character) || '';
    return view.editable ? `${reason} Double-click to write a perspective.` : reason;
}

export function perspectiveDependentsHint(count) {
    return count === 1
        ? '1 later perspective was built on this one.'
        : `${count} later perspectives were built on this one.`;
}

// null while the view of a story message is still on its way
export function perspectiveForMessage(message, perspectives) {
    if (!perspectives) return null;
    if (INTERFACE_ROW_TYPES.includes(message.type)) return INTERFACE_ROW_VIEW;
    if (message.type === 'narrator' && message.id == null) return perspectives.intro;
    return (message.id != null && perspectives.views[message.id]) || null;
}

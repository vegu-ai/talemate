/**
 * Shared websocket dispatchers for the entity-action surfaces (chat-view
 * tooltip via EntityHighlightMixin, WorldState.vue sidebar, creative tool
 * menu). Keeps the wire shape for the entity-level verbs in one place:
 *
 *   - "Call into scene" / "Take out of scene" (UI labels) →
 *     director.activate_character | director.deactivate_character
 *     `neverNarrate` skips the narrator's entry/exit narration, which the
 *     surfaces offer on the platform's primary modifier.
 *
 *   - "Add Detail" (UI label) → world_state_agent.examine_entity
 *     Expands the snapshot the user is looking at into a
 *     ContextInvestigationMessage. Requires a snapshot to seed from.
 *
 *   - "Look at" → narrator.look_at_character | narrator.query
 *     Fresh narrator-driven take. Characters use the dedicated handler when
 *     they map to a live Scene actor; everything else (unknown character
 *     names, items, places) falls through to narrator.query — backend
 *     handle_look_at_character would crash on unknown character names since
 *     scene.get_character returns None, and narrate_character(None, ...)
 *     trips downstream.
 */

function sendExamineEntity(ws, { name, kind, snapshot }) {
    ws.send(JSON.stringify({
        type: 'world_state_agent',
        action: 'examine_entity',
        entity_name: name,
        entity_kind: kind,
        snapshot_text: snapshot,
    }));
}

function sendLookAtCharacter(ws, name) {
    ws.send(JSON.stringify({
        type: 'narrator',
        action: 'look_at_character',
        character: name,
        narrative_direction: '',
    }));
}

function sendDescribeQuery(ws, name) {
    ws.send(JSON.stringify({
        type: 'narrator',
        action: 'query',
        query: `describe the appearance of ${name}.`,
    }));
}

function sendCharacterPresence(ws, { action, name, neverNarrate }) {
    ws.send(JSON.stringify({
        type: 'director',
        action,
        character_name: name,
        never_narrate: neverNarrate,
    }));
}

export function dispatchActivateCharacter(ws, { name, neverNarrate }) {
    if (!ws || !name) return;
    sendCharacterPresence(ws, { action: 'activate_character', name, neverNarrate: !!neverNarrate });
}

export function dispatchDeactivateCharacter(ws, { name, neverNarrate }) {
    if (!ws || !name) return;
    sendCharacterPresence(ws, { action: 'deactivate_character', name, neverNarrate: !!neverNarrate });
}

export function dispatchExamineEntity(ws, { name, kind, snapshot }) {
    if (!ws || !name || !kind || !snapshot) return;
    sendExamineEntity(ws, { name, kind, snapshot });
}

export function dispatchLookAtEntity(ws, { name, kind, isKnownCharacter }) {
    if (!ws || !name) return;
    if (kind === 'character' && isKnownCharacter) {
        sendLookAtCharacter(ws, name);
    } else {
        sendDescribeQuery(ws, name);
    }
}

// True when `name` resolves to a character that exists in this scene's active
// or inactive roster (the only names narrator.look_at_character can resolve).
// `sceneData` is the unpacked `.data` payload — both call sites get there
// via slightly different prop/inject paths, so callers do the unpacking.
export function isKnownSceneCharacter(sceneData, name) {
    if (!sceneData || !name) return false;
    const active = sceneData.characters || [];
    for (const c of active) {
        if (c?.name === name) return true;
    }
    // scene_status sends inactive_characters as a plain list of names
    const inactive = sceneData.inactive_characters || [];
    return inactive.includes(name);
}

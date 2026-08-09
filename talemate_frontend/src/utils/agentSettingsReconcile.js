// Reconciliation logic for the Agents settings page: keeping a working-copy
// agent entry in step with the live schema after a dynamic-registry op, and
// keeping a buffered scene overlay in step with what the backend stores.
// Both are pure decisions over the state handed in — the page owns the state
// itself and the side effects that follow.
import { normalizeSceneOverlay, serializeSceneOverlay } from '@/constants/sceneAgentSettings';

/**
 * The children listed in a registry action's `dynamic_children` blob.
 * Anything that is not a JSON array reads as "no children" — the blob is a
 * stored string that may predate the current shape.
 */
export function parseDynamicChildren(blob) {
    try {
        const parsed = JSON.parse(blob || '[]');
        return Array.isArray(parsed) ? parsed : [];
    } catch (_e) {
        return [];
    }
}

/**
 * Brings a working-copy agent entry's action membership in step with
 * `schemaActions` (an agent's live or freshly persisted action map), in
 * place.
 *
 * A registry op changes which child actions exist. Any working copy entry for
 * that agent predates the change — saving it as-is would push the stale
 * registry blob back and undo the add / remove. Reconcile the membership
 * only; field values the user has edited are left alone.
 */
export function reconcileDynamicChildren(entry, schemaActions) {
    if (!entry?.actions || !Object.keys(schemaActions).length) {
        // an empty action map means the agent reported no schema (e.g.
        // it is not instantiated) — not an instruction to drop actions
        return;
    }
    // A stored action carries no parent_key (that is schema, not value), so
    // an unregistered child is recognized by the registry whose stored blob
    // still lists it — captured BEFORE the blobs are synced to their new
    // values.
    const parentOfStoredChild = {};
    for (const [key, action] of Object.entries(entry.actions)) {
        for (const child of parseDynamicChildren(action?.config?.dynamic_children?.value)) {
            parentOfStoredChild[child.slug] = key;
        }
    }
    const registryKeys = new Set();
    for (const [key, schema] of Object.entries(schemaActions)) {
        if (schema.config?.dynamic_children) {
            registryKeys.add(key);
            if (entry.actions[key]?.config?.dynamic_children) {
                entry.actions[key].config.dynamic_children = { value: schema.config.dynamic_children.value };
            }
        }
        if (schema.parent_key && !entry.actions[key]) {
            const config = {};
            for (const [configKey, field] of Object.entries(schema.config || {})) {
                config[configKey] = { value: field.value };
            }
            entry.actions[key] = { enabled: schema.enabled, config: config };
        }
    }
    // only registry children are ours to drop — an action missing from the
    // live schema for any other reason (a build without that feature, a
    // partially reported agent) keeps its stored config
    for (const key of Object.keys(entry.actions)) {
        if (schemaActions[key]) {
            continue;
        }
        if (registryKeys.has(parentOfStoredChild[key])) {
            delete entry.actions[key];
        }
    }
}

function serializeSlice(overlay, actionKey) {
    const slice = overlay?.actions?.[actionKey];
    return slice ? serializeSceneOverlay({ actions: { [actionKey]: slice } }) : '';
}

/**
 * Three-way merge of a buffered scene overlay against what the backend now
 * stores, given the overlay the buffer was seeded from.
 *
 * `live` is the agent's stored overrides as they arrived over the wire; it is
 * normalized here, so the overlay handed back is never the payload every
 * message handler shares.
 *
 * Returns `{action, conflicts, merged, seed}`:
 *
 *   * `none`  — nothing buffered, there is nothing to reconcile;
 *   * `clear` — the buffer no longer says anything the stored state doesn't;
 *               stop shadowing the agent;
 *   * `keep`  — stored state is still what we started from, so the difference
 *               is just this page's unsaved edits;
 *   * `merge` — somebody else wrote to this agent's overrides: adopt `merged`
 *               as the buffer and `seed` as what it is now seeded from.
 *
 * `conflicts` lists the action keys the user had also edited — theirs is kept
 * and will overwrite the foreign write on save. It can be non-empty on a
 * `clear` too: a foreign write that agrees with the user's edit collides and
 * still leaves nothing left to buffer.
 */
export function mergeSceneOverrides({ buffered, seed, live }) {
    if (!buffered) {
        return { action: 'none', conflicts: [] };
    }
    const liveOverlay = normalizeSceneOverlay(live);
    if (serializeSceneOverlay(buffered) === serializeSceneOverlay(liveOverlay)) {
        // stored state caught up with the buffer — our commit landed (or
        // someone stored the same thing)
        return { action: 'clear', conflicts: [] };
    }
    const seedOverlay = seed || { actions: {} };
    if (serializeSceneOverlay(seedOverlay) === serializeSceneOverlay(liveOverlay)) {
        return { action: 'keep', conflicts: [] };
    }
    // The commit is a full-slice replace, so keeping the buffer as-is would
    // silently revert the foreign write; adopt it for every action the user
    // has not touched and report only what actually collides.
    const merged = { actions: { ...buffered.actions } };
    const conflicts = [];
    const keys = new Set([
        ...Object.keys(liveOverlay.actions),
        ...Object.keys(seedOverlay.actions),
        ...Object.keys(buffered.actions),
    ]);
    for (const key of keys) {
        const liveSlice = serializeSlice(liveOverlay, key);
        if (liveSlice === serializeSlice(seedOverlay, key)) {
            continue;
        }
        if (serializeSlice(buffered, key) !== serializeSlice(seedOverlay, key)) {
            conflicts.push(key);
            continue;
        }
        if (liveOverlay.actions[key]) {
            merged.actions[key] = JSON.parse(JSON.stringify(liveOverlay.actions[key]));
        } else {
            delete merged.actions[key];
        }
    }
    if (serializeSceneOverlay(merged) === serializeSceneOverlay(liveOverlay)) {
        return { action: 'clear', conflicts };
    }
    return { action: 'merge', conflicts, merged, seed: liveOverlay };
}

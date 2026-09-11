// The settings the knowledge hub owns. One set for the whole hub, derived from
// the toggles it shows and every key of both effort tables, so a group reset
// and the whole-hub reset clear the same keys and nothing outside them.
import { EFFORT_PRESETS, EFFORT_STOPS } from '@/constants/knowledgeEffort';
import { KNOWLEDGE_TOGGLES } from '@/utils/knowledgeHub';
import { effortKey, effortValueOf } from '@/utils/knowledgeEffort';
import { configOverrideActive, enabledOverrideActive } from '@/constants/sceneAgentSettings';

function buildOwned() {
    const owned = {};
    const add = (agent, action, key) => {
        const id = `${agent}.${action}`;
        if (!owned[id]) owned[id] = { agent, action, keys: new Set() };
        owned[id].keys.add(key);
    };
    for (const spec of KNOWLEDGE_TOGGLES) add(spec.agent, spec.action, spec.config ?? 'enabled');
    for (const mode of Object.keys(EFFORT_PRESETS)) {
        for (const stop of EFFORT_STOPS[mode]) {
            for (const key of Object.keys(EFFORT_PRESETS[mode][stop])) {
                const [agent, action, config] = key.split('.');
                add(agent, action, config);
            }
        }
    }
    return owned;
}

export const HUB_OWNED_OVERRIDES = Object.freeze(buildOwned());

/** The keys the hub owns on one action, or an empty list for an unknown one. */
export function ownedKeys(agent, action) {
    return [...(HUB_OWNED_OVERRIDES[`${agent}.${action}`]?.keys || [])];
}

/** The owned keys of one action that the overlay actually overrides. */
export function overriddenOwnedKeys(overlay, agent, action) {
    const keys = HUB_OWNED_OVERRIDES[`${agent}.${action}`]?.keys;
    if (!keys) return [];
    const slice = overlay?.actions?.[action];
    if (!slice) return [];
    const result = [];
    for (const key of keys) {
        if (key === 'enabled') {
            if (slice.enabled !== undefined && slice.enabled !== null) result.push(key);
        } else if (slice.config?.[key]) {
            result.push(key);
        }
    }
    return result;
}

/** True when any key the hub owns on that action is currently overridden. */
export function groupHasOwnedOverride(overlay, agent, action) {
    return overriddenOwnedKeys(overlay, agent, action).length > 0;
}

/** True when the action's own enable override is active — the master chip's case. */
export function masterOverrideActive(overlay, agent, action) {
    if (!HUB_OWNED_OVERRIDES[`${agent}.${action}`]?.keys.has('enabled')) return false;
    return enabledOverrideActive(overlay, action);
}

/** True when one owned config key is overridden, keyed the hub way. */
function effortKeyOverridden(agents, key) {
    const { agent: agentName, action: actionName, config } = effortKey(key);
    const agent = (agents || []).find((candidate) => candidate.name === agentName);
    const overlay = agent?.data?.scene_overrides || {};
    if (config === null) return enabledOverrideActive(overlay, actionName);
    return configOverrideActive(overlay, actionName, config);
}

/**
 * Where the current mode's effort controls come from. `present` is how many of
 * the mode's preset keys the status carries; `overridden` how many of those the
 * scene pins. `any` drives the "Scene override" chip, `complete` its "all"
 * tooltip; a partially global state is never relabelled as entirely owned.
 */
export function effortOverrideState(agents, mode) {
    const keys = new Set();
    for (const stop of EFFORT_STOPS[mode] || []) {
        for (const key of Object.keys(EFFORT_PRESETS[mode]?.[stop] || {})) keys.add(key);
    }
    let present = 0;
    let overridden = 0;
    for (const key of keys) {
        if (effortValueOf(agents, key) === undefined) continue;
        present += 1;
        if (effortKeyOverridden(agents, key)) overridden += 1;
    }
    return { present, overridden, any: overridden > 0, complete: present > 0 && overridden === present };
}

/** The clear entries that drop a whole group's owned overrides. */
export function groupClearEntries(agent, action) {
    return ownedKeys(agent, action).map((key) => (
        key === 'enabled' ? { agent, action } : { agent, action, config: key }
    ));
}

export function settingClearEntry(agent, action, config) {
    return { agent, action, config };
}

/** The clear entries that drop the whole hub's owned overrides across both modes. */
export function hubClearEntries() {
    return Object.values(HUB_OWNED_OVERRIDES).flatMap(({ agent, action }) => groupClearEntries(agent, action));
}

/** True when anything the hub owns — hidden keys included — is overridden. */
export function hubHasOverrides(agents) {
    for (const { agent, action } of Object.values(HUB_OWNED_OVERRIDES)) {
        const entry = (agents || []).find((candidate) => candidate.name === agent);
        if (groupHasOwnedOverride(entry?.data?.scene_overrides || {}, agent, action)) return true;
    }
    return false;
}

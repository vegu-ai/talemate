// Agent values the drawer wrote and the backend has not confirmed yet.
//
// A status frame can be older than a save still in flight: it was emitted
// before the backend applied the save. Every drawer save sends all agents, so
// a frame that put the old value back would let the next save of ANY agent
// write the old value again. Held values win over incoming frames until their
// save is answered.

const clone = (value) => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

/**
 * The values one agent_status frame reports, as plain data: the frame's
 * objects are shared with the drawer, which edits them in place.
 * Same shape as a held write, so restoring the truth is applying it.
 */
export function reportedValues(data) {
    const values = { enabled: data?.enabled, actions: {}, scene_overrides: clone(data?.scene_overrides || {}) };
    for (const [name, action] of Object.entries(data?.actions || {})) {
        const config = {};
        for (const [key, field] of Object.entries(action?.config || {})) {
            config[key] = clone(field?.value);
        }
        values.actions[name] = { enabled: action?.enabled, config };
    }
    return values;
}

/**
 * What the backend will report once the saves in flight are applied: the last
 * report with the pending holds over it, oldest first. A save diffed against
 * this gets a hold for a switch-back too, and that newer hold wins.
 */
export function expectedValues(reported, helds) {
    const expected = clone(reported || { actions: {} });
    expected.actions ||= {};
    for (const held of helds) {
        if ('enabled' in held) expected.enabled = held.enabled;
        for (const [name, entry] of Object.entries(held.actions || {})) {
            const action = (expected.actions[name] ||= { config: {} });
            if ('enabled' in entry) action.enabled = entry.enabled;
            Object.assign((action.config ||= {}), clone(entry.config || {}));
        }
    }
    return expected;
}

/** The values `agent` holds that differ from `reported`. */
export function writtenValues(reported, agent) {
    const held = { actions: {} };
    if (agent.enabled !== reported?.enabled) held.enabled = agent.enabled;
    for (const [name, action] of Object.entries(agent.actions || {})) {
        const before = reported?.actions?.[name];
        const entry = { config: {} };
        if (action?.enabled !== before?.enabled) entry.enabled = action?.enabled;
        for (const [key, field] of Object.entries(action?.config || {})) {
            if (!same(field?.value, before?.config?.[key])) entry.config[key] = clone(field?.value);
        }
        if ('enabled' in entry || Object.keys(entry.config).length) held.actions[name] = entry;
    }
    return held;
}

export function isEmptyWrite(held) {
    return !('enabled' in held) && !Object.keys(held.actions || {}).length && !held.scene_overrides && !held.scene_overrides_set;
}

// Sparse scene-override values over the agent's overlay: what another writer
// changed meanwhile stays.
function mergeSceneOverrides(overlay, set) {
    const actions = { ...(overlay?.actions || {}) };
    for (const [name, slice] of Object.entries(set.actions || {})) {
        const current = actions[name] || {};
        actions[name] = { ...current, config: { ...(current.config || {}), ...clone(slice.config || {}) } };
        if ('enabled' in slice) actions[name].enabled = slice.enabled;
    }
    return { ...(overlay || {}), actions };
}

/**
 * Puts held values over a freshly merged agent. New objects throughout: the
 * merged ones are shared with the frame and with other status readers.
 */
export function applyHeldValues(agent, held) {
    if ('enabled' in held) agent.enabled = held.enabled;
    for (const [name, entry] of Object.entries(held.actions || {})) {
        const action = agent.actions?.[name];
        if (!action) continue;
        const config = { ...action.config };
        for (const [key, value] of Object.entries(entry.config || {})) {
            if (config[key]) config[key] = { ...config[key], value: clone(value) };
        }
        agent.actions[name] = { ...action, config };
        if ('enabled' in entry) agent.actions[name].enabled = entry.enabled;
    }
    if (held.scene_overrides) {
        agent.data = { ...agent.data, scene_overrides: clone(held.scene_overrides) };
    }
    if (held.scene_overrides_set) {
        agent.data = { ...agent.data, scene_overrides: mergeSceneOverrides(agent.data?.scene_overrides, held.scene_overrides_set) };
    }
}

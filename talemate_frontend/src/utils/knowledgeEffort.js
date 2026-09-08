// Reads and writes the effort presets over the live agent_status entries, the
// way the knowledge hub reads its toggles. A key the status does not carry
// (the backend strips the other mode's keys) is left out of every comparison
// and every patch.
import { effectiveActionEnabled, effectiveConfigValue } from '@/constants/sceneAgentSettings';
import { EFFORT_PRESETS, EFFORT_STOPS, REQUEST_TOGGLES } from '@/constants/knowledgeEffort';
import { PERSPECTIVES_ANALYSIS_COST } from '@/utils/knowledgeHub';

export function effortMode(perspectives) {
    return perspectives ? 'perception' : 'legacy';
}

// A stop the target table lacks (Standard Ultra in Character perspectives)
// lands on that table's top stop.
export function stopForMode(stop, mode) {
    const stops = EFFORT_STOPS[mode];
    return stops.includes(stop) ? stop : stops[stops.length - 1];
}

function preset(mode, stop) {
    const table = EFFORT_PRESETS[mode]?.[stop];
    if (!table) throw new Error(`Unknown effort stop ${mode}.${stop}`);
    return table;
}

export function effortKey(key) {
    const [agent, action, config] = key.split('.');
    return { agent, action, config: config === 'enabled' ? null : config };
}

// undefined when the agent has not reported or the status lacks the key
export function effortValueOf(agents, key) {
    const { agent: agentName, action: actionName, config } = effortKey(key);
    const agent = (agents || []).find((candidate) => candidate.name === agentName);
    const action = agent?.actions?.[actionName];
    if (!action) return undefined;
    const overlay = agent.data?.scene_overrides || {};
    if (config === null) return !!effectiveActionEnabled(agent.actions, overlay, actionName);
    const field = action.config?.[config];
    if (!field) return undefined;
    const value = effectiveConfigValue(agent.actions, overlay, `${actionName}.config.${config}`);
    return field.type === 'bool' ? !!value : Number(value);
}

function matches(agents, preset) {
    let present = 0;
    let same = 0;
    for (const [key, value] of Object.entries(preset)) {
        const current = effortValueOf(agents, key);
        if (current === undefined) continue;
        present += 1;
        if (current === value) same += 1;
    }
    return { present, same };
}

/**
 * The stop the live toggles sit on: `stop` is a stop key, 'custom' when no
 * table row matches, or null while no agent has reported. `nearest` is the
 * row with the most matching keys, for placing the thumb of a custom state.
 */
export function currentEffort(agents, mode) {
    let nearest = null;
    let best = -1;
    let anyPresent = false;
    for (const stop of EFFORT_STOPS[mode]) {
        const { present, same } = matches(agents, EFFORT_PRESETS[mode][stop]);
        if (!present) continue;
        anyPresent = true;
        if (same === present) return { stop, nearest: stop };
        if (same > best) {
            best = same;
            nearest = stop;
        }
    }
    return anyPresent ? { stop: 'custom', nearest } : { stop: null, nearest: null };
}

/**
 * What has to change to reach `stop`, grouped per agent action:
 * [{ agent, action, enabled?, config: { key: value } }], only for keys the
 * status carries and whose value differs.
 */
export function effortPatch(agents, mode, stop) {
    const groups = [];
    for (const [key, value] of Object.entries(preset(mode, stop))) {
        const current = effortValueOf(agents, key);
        if (current === undefined || current === value) continue;
        const { agent, action, config } = effortKey(key);
        let group = groups.find((g) => g.agent === agent && g.action === action);
        if (!group) {
            group = { agent, action, config: {} };
            groups.push(group);
        }
        if (config === null) group.enabled = value;
        else group.config[config] = value;
    }
    return groups;
}

// What a stop costs per line, from the tables alone, so a mode the loaded
// scene is not in can be priced as well.
export function effortCost(mode, stop) {
    const table = preset(mode, stop);
    const extras = mode === 'perception' ? [PERSPECTIVES_ANALYSIS_COST] : [];
    for (const [key, label] of Object.entries(REQUEST_TOGGLES)) {
        if (table[key] === true) extras.push(label);
    }
    return {
        extras,
        text: extras.length ? `Extra requests: ${extras.join(', ')}` : 'No extra requests per line',
    };
}

// The stop the live toggles sit on, carried to the other mode's table: what
// both story-mode switches queue on the drawer before they send the change.
export function queueEffortAcrossSwitch(agents, toPerspectives, queue) {
    const { stop } = currentEffort(agents, effortMode(!toPerspectives));
    if (!stop || stop === 'custom') return null;
    const target = effortMode(toPerspectives);
    const carried = stopForMode(stop, target);
    queue(carried, target);
    return carried;
}

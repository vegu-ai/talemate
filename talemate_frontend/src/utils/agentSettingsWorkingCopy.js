// Working copy protocol for the Agents settings page: reading an agent's
// effective values (working copy first, live schema as fallback) and
// materializing them into a full persisted entry on the first edit.

import { hasOwnName } from './nameKeyedMap.js';

/**
 * The client name an `agent_status` payload reports: a plain client name for
 * LLM agents, a chip dict for agents that report more (the name then lives
 * under `client.client.value`). Null when there is none.
 */
export function liveClientName(agent) {
    const client = agent?.client;
    if (client && typeof client === 'object') {
        return client.client ? client.client.value : null;
    }
    return client || null;
}

/**
 * Whether the agent reads as enabled: the stored value when the working copy
 * has one, the live agent's state otherwise.
 */
export function agentEnabled(config, liveAgents, agentType) {
    const stored = config?.agents?.[agentType];
    if (stored && typeof stored.enabled === 'boolean') {
        return stored.enabled;
    }
    return !!liveAgents[agentType]?.data?.enabled;
}

/**
 * The client the agent reads as assigned to, or null.
 *
 * The running agent's assignment stands in for an unset one, but only while
 * the working copy still has that client — after it is removed there,
 * "unassigned" is the truth (the backend assigns a new one when the save is
 * applied).
 */
export function agentClient(config, liveAgents, agentType) {
    const stored = config?.agents?.[agentType];
    if (stored && stored.client) {
        return stored.client;
    }
    const live = liveClientName(liveAgents[agentType]);
    return (live && hasOwnName(config?.clients, live)) ? live : null;
}

/**
 * The agent's effective action values — an `{enabled, config: {key: {value}}}`
 * map over the live schema's actions, each field taking the stored value when
 * the working copy has one and the schema's current value otherwise. Schema
 * itself (labels, types, conditions) is never carried along.
 */
export function effectiveActionsFor(config, liveAgents, agentType) {
    const schemaActions = liveAgents[agentType]?.data?.actions || {};
    const storedActions = config?.agents?.[agentType]?.actions || {};
    const actions = {};
    for (const [key, schema] of Object.entries(schemaActions)) {
        const stored = storedActions[key] || {};
        const configValues = {};
        for (const [configKey, field] of Object.entries(schema.config || {})) {
            const storedValue = stored.config?.[configKey]?.value;
            configValues[configKey] = { value: storedValue === undefined ? field.value : storedValue };
        }
        actions[key] = {
            enabled: typeof stored.enabled === 'boolean' ? stored.enabled : schema.enabled,
            config: configValues,
        };
    }
    return actions;
}

/**
 * Builds the agent's complete persisted entry ({enabled, client, actions})
 * from its effective values into `config.agents[agentType]`, in place, and
 * returns it. Keys an existing entry carries beyond those three are kept.
 *
 * Always builds — the caller decides whether an agent still needs it.
 */
export function materializeAgentEntry(config, liveAgents, agentType) {
    if (!config.agents) {
        config.agents = {};
    }
    const data = liveAgents[agentType]?.data || {};
    const effective = effectiveActionsFor(config, liveAgents, agentType);
    const actions = {};
    for (const [key, values] of Object.entries(effective)) {
        const actionConfig = {};
        for (const [configKey, field] of Object.entries(values.config)) {
            actionConfig[configKey] = { value: field.value };
        }
        actions[key] = { enabled: values.enabled, config: actionConfig };
    }
    config.agents[agentType] = {
        ...(config.agents[agentType] || {}),
        enabled: agentEnabled(config, liveAgents, agentType),
        // agents that don't generate never carry a client
        client: data.requires_llm_client ? agentClient(config, liveAgents, agentType) : null,
        actions: actions,
    };
    return config.agents[agentType];
}

/**
 * The entry's slice for `actionKey`, creating it (and the structure around it)
 * when the entry does not carry it yet. Existing values are left alone.
 */
export function entryAction(entry, actionKey) {
    if (!entry.actions) {
        entry.actions = {};
    }
    if (!entry.actions[actionKey]) {
        entry.actions[actionKey] = { enabled: true, config: {} };
    }
    if (!entry.actions[actionKey].config) {
        entry.actions[actionKey].config = {};
    }
    return entry.actions[actionKey];
}

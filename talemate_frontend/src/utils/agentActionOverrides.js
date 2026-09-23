import { liveClientName } from './agentSettingsWorkingCopy.js';

export const REASONING_HINTS = {
    locked: 'always reasons — override ignored',
    off: 'reasoning off — override has no effect',
    on: 'reasoning on',
    unknown: 'reasoning state unknown',
};

/**
 * Split an override key on its first dot — an action name may contain dots,
 * an agent type never does.
 */
export function parseOverrideKey(key) {
    const idx = key.indexOf('.');
    if (idx < 0) {
        return { agentType: key, action: '' };
    }
    return { agentType: key.slice(0, idx), action: key.slice(idx + 1) };
}

/**
 * `liveClientName` for the app shell's `agentStatus` map, which keeps the
 * `agent_status` client field under `details`.
 */
export function agentClientName(agentEntry) {
    return liveClientName({ client: agentEntry?.details });
}

export function clientReasoningHint(client) {
    if (!client) {
        return { state: 'unknown', text: REASONING_HINTS.unknown };
    }
    if (client.reason_locked) {
        return { state: 'locked', text: REASONING_HINTS.locked };
    }
    if (!client.reasoning_override_applies) {
        return { state: 'off', text: REASONING_HINTS.off };
    }
    return { state: 'on', text: REASONING_HINTS.on };
}

export function overrideActive(override) {
    return !!override && Object.values(override).some(Boolean);
}

function matchesSearch(row, search) {
    const needle = (search || '').trim().toLowerCase();
    if (!needle) return true;
    return [row.key, row.agentLabel, row.action, row.description, row.clientName, row.servedByLabel, row.observedClientName]
        .filter(Boolean)
        .some((text) => text.toLowerCase().includes(needle));
}

/**
 * A row carries the owner agent's current client (`clientName`) and, when
 * the action's request is sent by another agent (`served_by`), that agent's
 * current client too (`observedClientName`), each with its own hint.
 */
export function buildOverrideRows({
    overrides = {},
    observed = [],
    agentStatus = {},
    clients = [],
    search = '',
    onlyOverridden = false,
    agentType = null,
} = {}) {
    const clientsByName = new Map(clients.map((client) => [client.name, client]));
    const observedByKey = new Map(observed.map((entry) => [entry.key, entry]));
    const keys = new Set([...Object.keys(overrides), ...observedByKey.keys()]);

    const rows = [];
    for (const key of keys) {
        const parsed = parseOverrideKey(key);
        const learned = observedByKey.get(key) || null;
        const agentEntry = agentStatus[parsed.agentType] || null;
        const clientName = agentClientName(agentEntry) || learned?.client_name || null;
        const servedBy = learned?.served_by && learned.served_by !== parsed.agentType ? learned.served_by : null;
        const observedClientName = servedBy
            ? agentClientName(agentStatus[servedBy]) || learned.client_name || null
            : null;
        const override = overrides[key] || null;
        const row = {
            key,
            agentType: parsed.agentType,
            agentLabel: agentEntry?.label || parsed.agentType,
            action: parsed.action,
            description: learned?.description || null,
            clientName,
            reasoning: clientReasoningHint(clientName ? clientsByName.get(clientName) : null),
            servedBy,
            servedByLabel: servedBy ? agentStatus[servedBy]?.label || servedBy : null,
            observedClientName,
            observedReasoning: observedClientName && observedClientName !== clientName
                ? clientReasoningHint(clientsByName.get(observedClientName))
                : null,
            override,
            disableReasoning: !!override?.disable_reasoning,
            learned: !!learned,
        };
        if (agentType && row.agentType !== agentType) continue;
        if (onlyOverridden && !overrideActive(override)) continue;
        if (!matchesSearch(row, search)) continue;
        rows.push(row);
    }

    return rows.sort((a, b) =>
        a.agentLabel.localeCompare(b.agentLabel) || a.action.localeCompare(b.action)
    );
}

export function countOverrides(overrides, agentType = null) {
    return Object.entries(overrides || {}).filter(
        ([key, override]) =>
            overrideActive(override) && (!agentType || parseOverrideKey(key).agentType === agentType)
    ).length;
}

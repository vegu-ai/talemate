// Attribution and recovery protocol for the Agents settings page's own
// `agent_config` requests. The router is shared with the drawer and the world
// editor, so an answer is ours only when it echoes an id we sent; a connection
// that dies takes every outstanding answer with it, and what those answers
// would have done has to be rebuilt from the next `app_config` broadcast.
import { reconcileDynamicChildren } from '@/utils/agentSettingsReconcile';

// The kinds of request this page sends — the only values `trackRequest`
// accepts and the only ones the transitions below compare against.
export const OP_KIND = Object.freeze({
    REGISTRY: 'registry',
    COMMIT: 'commit',
});

/**
 * A request id for the shared `agent_config` router. `seq` is the caller's
 * counter — distinct within one mount of the page — so two requests sent in
 * the same millisecond stay distinct.
 */
export function makeRequestId(seq) {
    return `agentcfg-${Date.now()}-${seq}`;
}

/**
 * Records an outstanding request of `kind` (an `OP_KIND` member) against the
 * agent it concerns, so its answer can be attributed and acted on.
 */
export function trackRequest(pendingOps, id, kind, agentType) {
    pendingOps[id] = { kind, agentType };
}

/**
 * The op `requestId` answers, retiring it, or null when the id is not one of
 * ours — a foreign answer leaves `pendingOps` untouched.
 */
export function attributeOperation(pendingOps, requestId) {
    const ours = pendingOps[requestId];
    if (!ours) {
        return null;
    }
    delete pendingOps[requestId];
    return ours;
}

/**
 * Whether a registry op is still outstanding. Its result is persisted
 * server-side but has not reached the working copy yet, so a save made now
 * would ship the pre-op membership and revert it.
 */
export function registryOpInFlight(pendingOps) {
    return Object.values(pendingOps).some(op => op.kind === OP_KIND.REGISTRY);
}

/**
 * Forgets every outstanding op, for when the socket they were sent on is gone
 * and nothing can answer them anymore. Registry ops leave a repair marked in
 * `registryRepairs` per agent.
 *
 * Dropping them loses no state: a registry op is persisted and broadcast
 * before it is answered, and the config is re-requested when the socket
 * reopens — so the `app_config` that follows carries the op and the repair the
 * answer would have done runs off that broadcast instead. A committed slice is
 * answered by an `agent_status`, which the backend re-emits for every agent on
 * connect, and its buffer survives a commit either way.
 */
export function dropPendingOps(pendingOps, registryRepairs) {
    for (const [id, op] of Object.entries(pendingOps)) {
        if (op.kind === OP_KIND.REGISTRY) {
            registryRepairs[op.agentType] = true;
        }
        delete pendingOps[id];
    }
}

/**
 * Forgets outstanding slice commits, whose answers have nothing left to report
 * on once the scene they were made against is gone. Registry ops are
 * scene-independent and stay pending.
 */
export function dropCommitOps(pendingOps) {
    for (const [id, op] of Object.entries(pendingOps)) {
        if (op.kind === OP_KIND.COMMIT) {
            delete pendingOps[id];
        }
    }
}

/**
 * Repairs the working copy of `agentType` from `persistedEntry`, the agent's
 * entry in the config the backend broadcast with a registry op — the state the
 * op was persisted into. The live schema is NOT that state yet: the completion
 * is queued directly while `agent_status` is debounced, so the broadcast is
 * all this has to go on.
 *
 * Returns true when the persisted entry replaced the working-copy entry
 * wholesale.
 */
export function adoptRegistryOp({ config, agentType, persistedEntry, materialize }) {
    if (!persistedEntry) {
        // no broadcast to build from — fall back to an entry off the (pre-op)
        // schema, which the agent_status that follows still reconciles the
        // membership into
        if (!config?.agents?.[agentType]) {
            materialize();
        }
        return false;
    }
    if (!config.agents) {
        config.agents = {};
    }
    if (!config.agents[agentType]) {
        // the working copy has no entry for this agent, so the next Save would
        // ship a config without it and drop the op — give it the persisted
        // one, which already carries the op
        config.agents[agentType] = JSON.parse(JSON.stringify(persistedEntry));
        return true;
    }
    // an entry that predates the op (loaded with it, or materialized by an
    // edit made while the op was in flight): its registry blob is the pre-op
    // one. The persisted actions carry the new membership in the shape the
    // reconciler reads.
    reconcileDynamicChildren(config.agents[agentType], persistedEntry.actions || {});
    return false;
}

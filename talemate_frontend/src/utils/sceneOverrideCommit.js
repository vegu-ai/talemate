// Scene-override protocol for the Agents settings page: the per-agent buffer
// edits accumulate in until the toolbar Save commits them, and the decisions
// the naming / commit flow makes before anything is sent.
import {
    DEFAULT_SCENE_AGENT_SETTINGS_FILENAME,
    normalizeSceneOverlay,
    serializeSceneOverlay,
    setActionOverrideSlice,
} from '@/constants/sceneAgentSettings';
import { dropCommitOps } from '@/utils/agentConfigOps';

// What a save should do about the buffered overrides — the only values
// `prepareCommitDecision` returns, and the only ones its callers may compare
// against.
export const COMMIT_DECISION = Object.freeze({
    NOTHING: 'nothing',
    BLOCKED_COMMIT_IN_FLIGHT: 'blocked-commit-in-flight',
    BLOCKED_UNAVAILABLE: 'blocked-unavailable',
    READY: 'ready',
    NEEDS_FILENAME: 'needs-filename',
});

function clearMap(map) {
    for (const key of Object.keys(map)) {
        delete map[key];
    }
}

/**
 * The overlay `agentType` reads as having: the buffered one when it is being
 * edited, the agent's stored overrides otherwise. An empty overlay when there
 * is no agent to read.
 *
 * The buffer overlays what the agent currently reports, the same way the
 * working copy overlays the live schema — an `agent_status` refresh must not
 * clobber unsaved edits.
 */
export function sceneOverlayFor({ buffer, liveAgents }, agentType) {
    if (!agentType) {
        return { actions: {} };
    }
    const buffered = buffer[agentType];
    if (buffered) {
        return buffered;
    }
    return normalizeSceneOverlay(liveAgents[agentType]?.data?.scene_overrides);
}

/**
 * The agent types whose buffered overlay differs from what the scene currently
 * has stored — the payloads a Save has to send. A buffer entry that says
 * nothing the stored state doesn't is not pending.
 */
export function pendingSceneAgents(buffer, liveAgents) {
    return Object.keys(buffer).filter((agentType) => {
        const live = normalizeSceneOverlay(liveAgents[agentType]?.data?.scene_overrides);
        return serializeSceneOverlay(buffer[agentType]) !== serializeSceneOverlay(live);
    });
}

/**
 * Buffers one action's override slice for `agentType`, in place.
 *
 * The first edit also seeds what the scene held when buffering started, so a
 * write from elsewhere can be told apart from our own edits; later edits keep
 * that seed. The buffered overlay stays sparse — an empty slice removes the
 * action instead of storing it.
 */
export function bufferOverrideSlice({ buffer, seed, liveAgents }, agentType, actionKey, slice) {
    const overlay = sceneOverlayFor({ buffer, liveAgents }, agentType);
    if (!buffer[agentType]) {
        seed[agentType] = normalizeSceneOverlay(overlay);
    }
    buffer[agentType] = {
        actions: setActionOverrideSlice(overlay.actions, actionKey, slice),
    };
}

/**
 * Forgets everything buffered against the scene that was loaded, in place, and
 * reports whether anything unsaved was lost (`{dropped}`) so the caller can say
 * so. Buffered overlays belong to the scene they were edited against; a
 * different (or unloaded) scene can't receive them, and answers to slices
 * committed against the previous one have nothing left to report on.
 */
export function resetForSceneChange({ buffer, seed, committingAgents, pendingOps }) {
    const dropped = Object.keys(buffer).length > 0;
    clearMap(buffer);
    clearMap(seed);
    clearMap(committingAgents);
    dropCommitOps(pendingOps);
    return { dropped };
}

/**
 * What a save should do about the buffered overrides, as a `COMMIT_DECISION`
 * member:
 *
 *   * `NOTHING`                   — nothing is pending, the save carries on;
 *   * `BLOCKED_COMMIT_IN_FLIGHT`  — the previous slice hasn't been answered
 *                                   yet; sending another would race the echo
 *                                   the buffer reconciles against;
 *   * `BLOCKED_UNAVAILABLE`       — this scene ignores overlays at runtime, so
 *                                   storing overrides would write into a void;
 *   * `READY`                     — the scene has a settings file to write to;
 *   * `NEEDS_FILENAME`            — the first override for this scene: it has
 *                                   to be named before it can be stored.
 */
export function prepareCommitDecision({ pending, commitInFlight, overridesAvailable, settingsFile }) {
    if (!pending) {
        return COMMIT_DECISION.NOTHING;
    }
    if (commitInFlight) {
        return COMMIT_DECISION.BLOCKED_COMMIT_IN_FLIGHT;
    }
    if (!overridesAvailable) {
        return COMMIT_DECISION.BLOCKED_UNAVAILABLE;
    }
    if (settingsFile) {
        return COMMIT_DECISION.READY;
    }
    return COMMIT_DECISION.NEEDS_FILENAME;
}

/**
 * Whether a first link to `filename`, on a scene with no link and no opt-out,
 * needs the scene saved as a copy first: the reload of a read-only scene
 * restores only the default file, through the auto-link.
 */
export function linkNeedsSceneCopy({ immutable, filename }) {
    return Boolean(immutable) && filename !== DEFAULT_SCENE_AGENT_SETTINGS_FILENAME;
}

/**
 * One full-slice replace per agent, in the order given. `overlayFor` reads the
 * overlay to send, `makeId` mints (and lets the caller track) the request id
 * each payload is answered by.
 *
 * Every payload carries the new `filename`, so a refused first link gives
 * the same actionable error for every pending agent.
 */
export function buildCommitPayloads({ agentTypes, overlayFor, filename, makeId }) {
    const payloads = [];
    for (const agentType of agentTypes) {
        const payload = {
            type: 'agent_config',
            action: 'save_scene_overrides',
            agent_type: agentType,
            // server-side `_prune_empty` cleans up empties on write
            override: overlayFor(agentType),
            request_id: makeId(agentType),
        };
        if (filename) {
            payload.filename = filename;
        }
        payloads.push(payload);
    }
    return payloads;
}

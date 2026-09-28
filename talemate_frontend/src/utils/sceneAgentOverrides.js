// The one writer for scene overrides outside the settings page. Every
// mutation goes through here as a sparse per-agent patch against the scene's
// current overlay, so an unrelated settings-page edit that lands first is not
// replaced, and a change made for one scene never touches the global agent
// values.
//
// Operations are serialized: one patch is in flight at a time and the next is
// dispatched only once the server acknowledges it by request id. A new hub
// action while one is in flight queues behind it; rapid slider choices are
// coalesced by the caller before they reach this writer. The coordinator is
// bound to the scene generation it started in — work queued for a scene that
// unloads is discarded rather than written into whatever loads next.
import { DEFAULT_SCENE_AGENT_SETTINGS_FILENAME } from '@/constants/sceneAgentSettings';
import { replyAfterAll } from '@/utils/writeReply';

let requestSeq = 0;
const nextRequestId = () => `hub-overrides-${Date.now().toString(36)}-${(++requestSeq).toString(36)}`;

/** The identity carried by a scene_status payload: the scene, not its contents. */
export function sceneIdentityOfData(data) {
    if (!data) return null;
    if (data.id) return String(data.id);
    const parts = [data.project_name, data.filename].filter(Boolean);
    return parts.length ? parts.join('/') : null;
}

/** The identity a patch is pinned to: the loaded scene, not its contents. */
export function sceneIdentityOf(scene) {
    return sceneIdentityOfData(scene?.data);
}

/** A saved scene is the only one whose overrides can reach disk. */
export function sceneCanPersist(scene) {
    const data = scene?.data;
    return Boolean(data?.filename && data?.project_name);
}

export class SceneAgentOverridesCoordinator {
    constructor({ getWebsocket, scene, state, onError, requestSave } = {}) {
        this.getWebsocket = getWebsocket || (() => null);
        this.getScene = scene || (() => null);
        this.state = state || null;
        this.onError = onError || (() => {});
        this.requestSave = requestSave;
        this.awaitingSave = false;
        this.saveRequired = false;
        this.confirmedSaveIdentity = null;
        this.queue = [];
        this.inFlight = null;
        this.identity = sceneIdentityOf(this.getScene());
        this.linked = Boolean(this.sceneLink());
        // A filename we just sent is not on the scene yet; a null link report
        // that crosses it must not be read as a World Editor unlink.
        this.linkPending = false;
        // A batch can fail on one agent and still succeed on the next; the
        // failure has to survive those later successes until the next action.
        this.failed = false;
        this.syncState();
    }

    get busy() {
        return this.inFlight !== null || this.queue.length > 0;
    }

    /** The agent-settings file the live scene reports, if any. */
    sceneLink() {
        return this.getScene()?.data?.agent_settings_file || null;
    }

    syncState() {
        if (!this.state) return;
        this.state.busy = this.busy;
        this.state.pendingSave = this.saveRequired && this.queue.length > 0;
        this.state.savingScene = this.awaitingSave;
        this.state.pendingLabel = this.queue[0]?.label || null;
    }

    /**
     * Drop everything queued or in flight and forget the scene generation — a
     * scene load start/failure, a disconnect, or an unmount. The next
     * `scene_status` binds the new generation.
     */
    reset(
        reason = 'The scene changed before the change was sent.',
        lost = 'The scene changed before the answer arrived; the change may have been saved.',
    ) {
        const inFlight = this.inFlight;
        const queued = this.queue;
        this.awaitingSave = false;
        this.saveRequired = false;
        this.confirmedSaveIdentity = null;
        this.queue = [];
        this.inFlight = null;
        this.identity = null;
        this.linked = false;
        this.linkPending = false;
        this.failed = false;
        if (this.state) this.state.error = null;
        this.syncState();
        // the backend may have stored a patch that was sent; its answer is lost
        inFlight?.reply?.onError(lost, false, true);
        for (const op of queued) op.reply?.onError(reason);
    }

    /**
     * Bind to the generation a scene_status frame reports. A different
     * generation invalidates queued work so it can never land in the new scene.
     */
    bindScene(data) {
        const identity = sceneIdentityOfData(data);
        if (!identity) return;
        if (this.identity !== identity) {
            this.reset();
            this.identity = identity;
        }
        this.reconcileLink(data?.agent_settings_file || null);
        if (!data.filename || !data.project_name) this.confirmedSaveIdentity = null;
        this.syncState();
    }

    /** Follow the scene's confirmed link state, keeping a just-sent link alive. */
    reconcileLink(reported) {
        if (reported) {
            this.linked = true;
            this.linkPending = false;
            return;
        }
        // A null report can be a frame emitted before our first link landed;
        // while a filename is in flight, keep the optimistic link.
        if (this.linkPending) return;
        this.linked = false;
    }

    /**
     * entries: [{ agent, action, enabled?, config: { key: value } }]
     * reply: {onComplete, onError(message, applyFailed, unknown)} for the whole
     * change, once; `unknown` when a sent patch lost its answer and may be stored.
     */
    applySceneAgentValues(entries, label = null, reply = null) {
        this.enqueueGroups(entries, (group, entry) => {
            const action = { config: {} };
            if (entry.enabled !== undefined) action.enabled = entry.enabled;
            for (const [key, value] of Object.entries(entry.config || {})) action.config[key] = { value };
            const existing = group.set.actions[entry.action] || {};
            group.set.actions[entry.action] = {
                ...existing,
                ...action,
                config: { ...(existing.config || {}), ...action.config },
            };
        }, label, reply);
    }

    /** entries: [{ agent, action, config? }] — no config clears the enable override. */
    clearSceneAgentValues(entries, reply = null) {
        this.enqueueGroups(entries, (group, entry) => {
            group.clear.push(entry.config ? { action: entry.action, config: entry.config } : { action: entry.action });
        }, null, reply);
    }

    enqueueGroups(entries, add, label = null, reply = null) {
        const scene = this.getScene();
        if (!sceneCanPersist(scene) && !this.requestSave) {
            this.report('Save the scene to change its scene overrides.');
            reply?.onError('Save the scene to change its scene overrides.');
            return;
        }
        const identity = sceneIdentityOf(scene);
        if (this.saveRequired) {
            reply?.onError('An earlier change is waiting for the scene to be saved.');
            return;
        }
        if (this.identity === null) this.identity = identity;
        if (!identity || identity !== this.identity) {
            reply?.onError('The scene changed before the change was saved.');
            return;
        }

        // A deliberate new hub action is what clears a retained partial-batch
        // failure — not the success of a later agent in the same batch.
        this.failed = false;
        this.report(null);

        const groups = new Map();
        for (const entry of entries || []) {
            const group = groups.get(entry.agent) || { set: { actions: {} }, clear: [] };
            add(group, entry);
            groups.set(entry.agent, group);
        }
        const answer = replyAfterAll(reply, groups.size);
        for (const [agent, patch] of groups) {
            this.queue.push({ agent, patch, identity, label, reply: answer, requestId: nextRequestId() });
        }
        this.syncState();
        this.dispatch();
    }

    dispatch() {
        if (this.inFlight || !this.queue.length) {
            this.syncState();
            return;
        }
        const scene = this.getScene();
        const op = this.queue[0];
        if (sceneIdentityOf(scene) !== op.identity) {
            // the scene moved on while this waited — never write into the next one
            this.reset();
            return;
        }
        if (this.saveRequired) return;
        if (!sceneCanPersist(scene) && this.confirmedSaveIdentity !== op.identity) {
            this.saveRequired = true;
            this.retrySave();
            return;
        }
        this.queue.shift();
        const payload = {
            type: 'agent_config',
            action: 'save_scene_overrides',
            agent_type: op.agent,
            request_id: op.requestId,
            scene_identity: op.identity,
            patch: op.patch,
        };
        const link = this.sceneLink();
        if (link) {
            // the scene already reports a link — never switch files under the user
            this.linked = true;
            this.linkPending = false;
        } else if (!this.linked) {
            payload.filename = DEFAULT_SCENE_AGENT_SETTINGS_FILENAME;
            this.linkPending = true;
        }
        this.inFlight = op;
        this.syncState();
        this.getWebsocket().send(JSON.stringify(payload));
    }

    async retrySave() {
        const op = this.queue[0];
        if (!op || !this.saveRequired || this.awaitingSave) return;
        this.awaitingSave = true;
        this.report(null);
        this.syncState();
        let result;
        try {
            result = await this.requestSave();
        } catch (error) {
            result = { status: 'failed', message: error.message };
        }
        if (this.queue[0] !== op) return;
        this.awaitingSave = false;
        if (sceneIdentityOf(this.getScene()) !== op.identity) {
            this.reset();
            return;
        }
        if (result?.status === 'saved' && result.identity === op.identity) {
            this.confirmedSaveIdentity = op.identity;
            this.saveRequired = false;
            this.dispatch();
        } else {
            this.report(result?.status === 'failed' ? result.message : 'Save cancelled. Your change is still pending.');
        }
        this.syncState();
    }

    discardPendingSave() {
        if (!this.saveRequired || this.awaitingSave) return;
        this.reset('The change was discarded.');
        this.bindScene(this.getScene()?.data);
    }

    report(message) {
        if (this.state) this.state.error = message || null;
        if (message) this.onError(message);
    }

    handleMessage(data) {
        if (!data) return;
        // Load start, load completion, failure and teardown all invalidate the
        // generation. `scene.loaded` carries no identity, so the binding comes
        // from the later `scene_status` — a fast load can deliver loaded first.
        if (data.type === 'system' && ['scene.loading', 'scene.loaded', 'scene.load_failure', 'scene.closed'].includes(data.id)) {
            this.reset();
            return;
        }
        if (data.type === 'scene_status') {
            this.bindScene(data.data);
            return;
        }
        if (data.type !== 'agent_config' || data.action !== 'operation_done') return;
        const id = data.request_id;
        if (!id || !this.inFlight || id !== this.inFlight.requestId) return;
        // Answered: any pre-link frame was emitted before this ack, so the link
        // state reported from here on is trustworthy.
        this.linkPending = false;
        if (data.error) {
            // No retry loop: surface the failure and let the status frames show
            // the resulting (possibly partial) effective state. A later success
            // in the same batch must not clear it.
            this.failed = true;
            this.report(data.error.message || 'The scene override could not be saved.');
            this.inFlight.reply?.onError(data.error.message || 'The scene override could not be saved.');
        } else {
            this.linked = true;
            if (!this.failed) this.report(null);
            this.inFlight.reply?.onComplete();
        }
        this.inFlight = null;
        this.syncState();
        this.dispatch();
    }
}

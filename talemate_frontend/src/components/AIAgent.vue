<template>
    <v-list-subheader class="text-uppercase">
        <v-icon>mdi-transit-connection-variant</v-icon>
        Agents
        <v-tooltip location="top" text="Manage agent action overrides — per-action settings such as turning reasoning off">
            <template #activator="{ props }">
                <v-btn
                    v-bind="props"
                    @click="openAgentActionOverrides()"
                    size="x-small"
                    variant="tonal"
                    color="primary"
                    prepend-icon="mdi-tune"
                    class="ml-2 text-none"
                    data-testid="agent-action-overrides-door"
                >
                    Agent action overrides
                    <v-chip v-if="overrideCount > 0" size="x-small" label color="primary" variant="flat" class="ml-1">{{ overrideCount }}</v-chip>
                </v-btn>
            </template>
        </v-tooltip>
    </v-list-subheader>
    <div v-if="isConnected()">
        <v-list density="compact">
            <!-- Ctrl + click toggles agent enable/disable when allowed -->
            <v-list-item  v-for="(agent, index) in state.agents" :key="index" @click="listItemClicked($event, agent)">
                <v-list-item-title>
                    <v-progress-circular v-if="agent.status === 'busy'" indeterminate="disable-shrink" color="primary"
                        size="14"></v-progress-circular>
                    <v-progress-circular v-else-if="agent.status === 'busy_bg'" indeterminate="disable-shrink" color="secondary"
                        size="14"></v-progress-circular>
                    <v-icon v-else-if="agent.status === 'uninitialized'" color="warning" size="14">mdi-checkbox-blank-circle</v-icon>
                    <v-icon v-else-if="agent.status === 'disabled'" color="muted" size="14">mdi-checkbox-blank-circle</v-icon>
                    <v-icon v-else-if="agent.status === 'error'" color="delete" size="14">mdi-checkbox-blank-circle</v-icon>
                    <v-icon v-else color="success" size="14">mdi-checkbox-blank-circle</v-icon>

                    <span class="ml-1" v-if="agent.label"> {{ agent.label }}</span>
                    <span class="ml-1" v-else> {{ agent.name }}</span>
                    <v-tooltip v-if="agent.data.experimental" text="Experimental" density="compact">
                        <template v-slot:activator="{ props }">
                            <v-icon v-bind="props" color="warning" size="14" class="ml-1">mdi-flask-outline</v-icon>
                        </template>
                    </v-tooltip>
                    <v-tooltip v-if="sceneOverrideCount(agent) > 0" :text="sceneOverrideTooltip(agent)" density="compact">
                        <template v-slot:activator="{ props }">
                            <v-icon v-bind="props" color="primary" size="14" class="ml-1">mdi-movie-open-cog-outline</v-icon>
                        </template>
                    </v-tooltip>
                    <AgentMessages :ref="el => setAgentMessageRef(el, agent.name)" v-if="agentHasMessages[agent.name]" :messages="messages[agent.name] || []" :agent="agent.name" :messageReceiveTime="agentHasMessages[agent.name]" />

                </v-list-item-title>
                
                <div class="d-flex flex-wrap align-center chip-container" v-if="agent.enabled">
                    <!-- Client chip for string type -->
                    <v-chip v-if="typeof(agent.client) === 'string'" 
                        prepend-icon="mdi-network-outline" 
                        size="x-small" 
                        color="muted" 
                        variant="tonal" 
                        label>
                        {{ agent.client }}
                    </v-chip>

                    <!-- Client chips for object type -->
                    <template v-else-if="typeof(agent.client) === 'object'">
                        <v-tooltip v-for="(detail, key) in agent.client" :key="key" :text="detail.description" >
                            <template v-slot:activator="{ props }">
                                <v-chip 
                                size="x-small" 
                                v-bind="props"
                                :prepend-icon="detail.icon"
                                label
                                :color="detail.color || 'muted'"
                                variant="tonal"
                                >
                                {{ detail.value }}
                                </v-chip>
                            </template>
                        </v-tooltip>
                    </template>

                    <div v-if="agentStateNotifications[agent.name]">
                        <v-tooltip v-for="(state, key) in agentStateNotifications[agent.name]" :key="key" :text="state.value" >
                            <template v-slot:activator="{ props }">
                                <v-chip v-bind="props" size="x-small" label variant="tonal" :color="state.color || 'highlight5'" prepend-icon="mdi-bell-outline">
                                    {{ state.key }}
                                </v-chip>
                            </template>
                        </v-tooltip>
                    </div>

                    <!-- Quick toggle action chips with their sub-config chips -->
                    <template v-for="(action, action_name) in agent.actions" :key="action_name">
                        <template v-if="actionEnabled(agent, action_name) && action.config && agent.enabled">
                            <v-tooltip
                                v-for="(config, config_name) in getRootQuickToggleConfigs(action)"
                                :key="`${action_name}-${config_name}-root`"
                                :text="configChipTooltip(agent, action_name, config_name, config)"
                                density="compact"
                            >
                                <template v-slot:activator="{ props }">
                                    <v-chip
                                        v-bind="props"
                                        size="x-small"
                                        label
                                        :color="configValue(agent, action_name, config_name) ? 'success' : 'muted'"
                                        variant="tonal"
                                        :prepend-icon="config.icon"
                                        @click.stop="toggleSubConfig(agent, action_name, config_name, config)"
                                    >
                                        {{ config.label }}
                                        <v-icon class="ml-1" size="small" v-if="configValue(agent, action_name, config_name)">mdi-check-circle-outline</v-icon>
                                        <v-icon class="ml-1" size="small" v-else>mdi-circle-outline</v-icon>
                                        <v-icon class="ml-1" size="x-small" color="primary" v-if="isConfigOverridden(agent, action_name, config_name)">mdi-movie-open-cog-outline</v-icon>
                                    </v-chip>
                                </template>
                            </v-tooltip>
                        </template>
                        <!-- Action chip (if it has quick_toggle) -->
                        <template v-if="action.quick_toggle && agent.enabled">
                            <v-tooltip :text="actionChipTooltip(agent, action_name, action)" density="compact">
                                <template v-slot:activator="{ props }">
                                    <v-chip
                                        v-bind="props"
                                        size="x-small"
                                        label
                                        :color="actionEnabled(agent, action_name) ? 'success' : 'muted'"
                                        variant="tonal"
                                        :prepend-icon="action.icon"
                                        @click.stop="toggleAction(agent, action_name, action)"
                                    >
                                        {{ action.label }}
                                        <v-icon class="ml-1" size="small" v-if="actionEnabled(agent, action_name)">mdi-check-circle-outline</v-icon>
                                        <v-icon class="ml-1" size="small" v-else>mdi-circle-outline</v-icon>
                                        <v-icon class="ml-1" size="x-small" color="primary" v-if="isEnabledOverridden(agent, action_name)">mdi-movie-open-cog-outline</v-icon>
                                    </v-chip>
                                </template>
                            </v-tooltip>
                        </template>
                        <!-- Related sub-config chips (if action is enabled) -->
                        <template v-if="actionEnabled(agent, action_name) && action.config && agent.enabled">
                            <v-tooltip
                                v-for="(config, config_name) in getQuickToggleSubConfigs(action)"
                                :key="`${action_name}-${config_name}`"
                                :text="configChipTooltip(agent, action_name, config_name, config)"
                                density="compact"
                            >
                                <template v-slot:activator="{ props }">
                                    <v-chip
                                        v-bind="props"
                                        size="x-small"
                                        label
                                        :color="configValue(agent, action_name, config_name) ? 'highlight3' : 'muted'"
                                        variant="tonal"
                                        @click.stop="toggleSubConfig(agent, action_name, config_name, config)"
                                    >
                                        {{ config.label }}
                                        <v-icon class="ml-1" size="x-small" v-if="configValue(agent, action_name, config_name)">mdi-check-circle-outline</v-icon>
                                        <v-icon class="ml-1" size="x-small" v-else>mdi-circle-outline</v-icon>
                                        <v-icon class="ml-1" size="x-small" color="primary" v-if="isConfigOverridden(agent, action_name, config_name)">mdi-movie-open-cog-outline</v-icon>
                                    </v-chip>
                                </template>
                            </v-tooltip>
                        </template>
                    </template>
                </div>
            </v-list-item>
        </v-list>
    </div>
</template>

<script>
import { isPrimaryModifier } from '@/utils/keyboardModifiers';
import { countOverrides } from '@/utils/agentActionOverrides';
import { effortMode, effortPatch, effortPinPatch } from '@/utils/knowledgeEffort';
import { perspectivesEnabled } from '@/utils/sceneSettings';
import { SceneAgentOverridesCoordinator, sceneIdentityOf } from '@/utils/sceneAgentOverrides';
import { replyAfterAll } from '@/utils/writeReply';
import { applyHeldValues, expectedValues, isEmptyWrite, reportedValues, writtenValues } from '@/utils/pendingAgentWrites';
import AgentMessages from './AgentMessages.vue';
import {
    configOverrideActive,
    countSceneOverrides,
    effectiveActionEnabled,
    effectiveConfigValue,
    enabledOverrideActive,
    setActionOverrideSlice,
} from '@/constants/sceneAgentSettings';

const EFFORT_AGENTS = ['conversation', 'summarizer', 'memory'];
const PENDING_EFFORT_TTL = 30000;

export default {
    components: {
        AgentMessages
    },
    emits: ['agents-updated'],

    data() {
        return {
            pendingEffort: null,
            // request id -> {reply, release} of a scene override slice in flight
            sliceReplies: {},
            sliceSeq: 0,
            // agent name -> reportedValues() of its last status frame
            lastReported: {},
            // agent name -> [{id, held}] written by a save not answered yet
            pendingWrites: {},
            pendingWriteSeq: 0,
            // shared by every open hub: one scene-only writer, one busy flag
            overridesState: { busy: false, error: null },
            // the story mode of the last scene status frame
            sceneMode: 'legacy',
            state: {
                agents: [],
            },
            maxMessagesPerAgent: 25,
            agentHasMessages: {},
            messages: {},
            agentMessagesRefs: {},
        }
    },
    props: {
        agentState: {
            type: Object,
            default: () => ({})
        },
        appConfig: Object,
        scene: Object,
    },
    computed: {
        overrideCount() {
            return countOverrides(this.appConfig?.agent_actions?.overrides);
        },
        agentStateNotifications() {
            // if key begins with 'notify__' and value is a string, return the key and value
            // return the notify__(.+) part as the key, and the value as the value
            // the key will also be title-ized (title and space instead of underscore)

            // this is done per agent, so we need to iterate over the agents and return a dict
            // with the agent name as the key and the notifications as the value (a list of dicts)
            let notifications = {};
            for(let agent in this.agentState) {
                notifications[agent] = Object.keys(this.agentState[agent]).filter(key => key.startsWith('notify__') && typeof this.agentState[agent][key] === 'string').map(key => {
                    return {
                        key: key.replace('notify__', '').replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase()),
                        value: this.agentState[agent][key]
                    }
                });
            }
            return notifications;
        }
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'isConnected',
        'getClients',
        'openAgentActionOverrides',
        'openAgentSettings',
        'requestSceneSave',
    ],
    methods: {
        // The scene-only write path outside the settings page. A sparse
        // per-agent patch, so a delayed change never replaces an unrelated edit
        // that landed first.
        applySceneAgentValues(entries, label, reply = null) {
            this.overrides?.applySceneAgentValues(entries, label, reply);
        },
        clearSceneAgentValues(entries, reply = null) {
            this.overrides?.clearSceneAgentValues(entries, reply);
        },
        sceneOverrideCount(agent) {
            return countSceneOverrides(agent?.data?.scene_overrides);
        },
        sceneOverrideTooltip(agent) {
            const n = this.sceneOverrideCount(agent);
            const file = this.scene?.data?.agent_settings_file || 'agent-settings.json';
            return `${n} scene override${n === 1 ? '' : 's'} active (from ${file})`;
        },

        setAgentMessageRef(el, agentName) {
            if (el) {
                this.agentMessagesRefs[agentName] = el;
            } else {
                delete this.agentMessagesRefs[agentName];
            }
        },
        /**
         * Handles clicks on an agent list item.
         *
         * Behaviour:
         *  - Regular click takes the user to the agent's settings page.
         *  - Ctrl-/Cmd-click toggles the agent's enabled state **iff** the agent supports toggling (agent.data.has_toggle).
         */
        listItemClicked(event, agent) {
            // If the user is holding Ctrl (Windows/Linux) or Cmd (macOS)
            if (isPrimaryModifier(event)) {
                // Only toggle agents that explicitly allow it
                if (agent.data && agent.data.has_toggle) {
                    agent.enabled = !agent.enabled;
                    this.saveAgent(agent);
                    agent.status = agent.enabled ? 'idle' : 'disabled';
                }
                event.preventDefault();
                return;
            }

            // Fallback to default behaviour – open the agent's settings page
            this.openAgentSettings(agent.name);
        },
        configurationRequired() {
            let clients = this.getClients();

            const agentErrors = [];

            for(let i = 0; i < this.state.agents.length; i++) {
                let agent = this.state.agents[i];

                // any agent erroring should be explicitly returned
                if(agent.status === 'error') {
                    return true;
                }

                if(!agent.data.requires_llm_client || agent.meta.essential === false)
                    continue

                if(agent.status === 'warning' || agent.status === 'error' || agent.status === 'uninitialized') {
                    return true;
                }

                // loop through all clients until we find the client assigned
                // to the agent, then check the client status to see if it's ok
                for(let j = 0; j < clients.length; j++) {
                    let client = clients[j];
                    if(client.name === agent.client) {
                        if(client.status === 'warning' || client.status === 'error' || client.status === 'disabled') {
                            return true;
                        }
                    }
                }
            }

            return false;
        },
        // ------------------------------------------------------------------
        // Quick-toggle chips — scene-aware reads and writes
        //
        // A chip must show what the loaded scene actually runs on: the scene
        // override when one is active, the global value otherwise. Its click
        // writes to whichever of the two it is showing, so the chip never
        // changes a value other than the one displayed.
        // ------------------------------------------------------------------

        sceneOverlay(agent) {
            return agent.data.scene_overrides || {};
        },
        actionEnabled(agent, action_name) {
            return effectiveActionEnabled(agent.actions, this.sceneOverlay(agent), action_name);
        },
        isEnabledOverridden(agent, action_name) {
            return enabledOverrideActive(this.sceneOverlay(agent), action_name);
        },
        configValue(agent, action_name, config_name) {
            return effectiveConfigValue(
                agent.actions,
                this.sceneOverlay(agent),
                `${action_name}.config.${config_name}`,
            );
        },
        isConfigOverridden(agent, action_name, config_name) {
            return configOverrideActive(this.sceneOverlay(agent), action_name, config_name);
        },
        actionChipTooltip(agent, action_name, action) {
            if (this.isEnabledOverridden(agent, action_name)) {
                return `Scene override — toggles ${action.label} for this scene only (global: ${action.enabled ? 'on' : 'off'})`;
            }
            return `Toggles ${action.label} globally`;
        },
        configChipTooltip(agent, action_name, config_name, config) {
            if (this.isConfigOverridden(agent, action_name, config_name)) {
                // `config` is the global entry the template iterates, so its
                // value is the one the override masks.
                return `Scene override — toggles ${config.label} for this scene only (global: ${config.value ? 'on' : 'off'})`;
            }
            return `Toggles ${config.label} globally`;
        },
        /**
         * Persist a changed per-action override slice. The server replaces the
         * whole per-agent slice, so the full overlay goes over the wire.
         */
        saveSceneOverrideSlice(agent, action_name, slice, reply = null) {
            const overlay = {
                actions: setActionOverrideSlice(this.sceneOverlay(agent).actions || {}, action_name, slice),
            };
            // Keep the local copy in sync so the chip updates immediately
            // instead of waiting for the agent status echo.
            agent.data.scene_overrides = overlay;
            const payload = {
                type: 'agent_config',
                action: 'save_scene_overrides',
                agent_type: agent.name,
                override: overlay,
                request_id: `drawer-slice-${Date.now()}-${++this.sliceSeq}`,
            };
            this.sliceReplies[payload.request_id] = {
                reply,
                release: this.holdWrite(agent.name, { actions: {}, scene_overrides: overlay }),
            };
            this.getWebsocket().send(JSON.stringify(payload));
        },
        // Returns release(restore): call it once the write is answered.
        // `restore` puts the last reported values back — a refused write
        // stored nothing, and the frame that said so was masked by the hold.
        holdWrite(agentName, held) {
            if (isEmptyWrite(held)) return () => {};
            const id = ++this.pendingWriteSeq;
            (this.pendingWrites[agentName] ||= []).push({ id, held });
            return (restore = false) => {
                const rest = (this.pendingWrites[agentName] || []).filter((write) => write.id !== id);
                if (rest.length) this.pendingWrites[agentName] = rest;
                else delete this.pendingWrites[agentName];
                const agent = this.state.agents.find((candidate) => candidate.name === agentName);
                if (restore && agent && this.lastReported[agentName]) {
                    applyHeldValues(agent, this.lastReported[agentName]);
                    this.reapplyPendingWrites(agent);
                }
            };
        },
        reapplyPendingWrites(agent) {
            for (const { held } of this.pendingWrites[agent.name] || []) {
                applyHeldValues(agent, held);
            }
        },
        toggleAction(agent, action_name, action) {
            if (this.isEnabledOverridden(agent, action_name)) {
                const slice = JSON.parse(JSON.stringify(this.sceneOverlay(agent).actions[action_name]));
                slice.enabled = !slice.enabled;
                this.saveSceneOverrideSlice(agent, action_name, slice);
                return;
            }

            // Toggle the action's enabled state
            action.enabled = !action.enabled;

            // Update the agent's actions
            agent.actions[action_name].enabled = action.enabled;

            // Save the agent to persist the changes
            this.saveAgent(agent);
        },
        toggleSubConfig(agent, action_name, config_name, config) {
            if (this.isConfigOverridden(agent, action_name, config_name)) {
                const slice = JSON.parse(JSON.stringify(this.sceneOverlay(agent).actions[action_name]));
                slice.config[config_name] = { value: !slice.config[config_name].value };
                this.saveSceneOverrideSlice(agent, action_name, slice);
                return;
            }

            // Toggle the config value (assuming it's a boolean)
            config.value = !config.value;

            // Update the agent's config
            agent.actions[action_name].config[config_name].value = config.value;

            // Save the agent to persist the changes
            this.saveAgent(agent);
        },
        // Every change of one agent action in one write: values already under a
        // scene override go to the override slice, the rest to the agent, each
        // saved once. Returns false when the action is unknown. `reply`
        // ({onComplete, onError}) hears the backend's answer to the change.
        applyActionValues(agent, action_name, { enabled, config = {} } = {}, reply = null) {
            const action = agent?.actions?.[action_name];
            if (!action) return false;
            let slice = null;
            const overrideSlice = () => {
                if (!slice) slice = JSON.parse(JSON.stringify(this.sceneOverlay(agent).actions[action_name]));
                return slice;
            };
            let agentChanged = false;
            const restores = [];
            if (enabled !== undefined) {
                if (this.isEnabledOverridden(agent, action_name)) {
                    if (this.sceneOverlay(agent).actions[action_name].enabled !== enabled) overrideSlice().enabled = enabled;
                } else if (action.enabled !== enabled) {
                    const previous = action.enabled;
                    action.enabled = enabled;
                    restores.push(() => { if (action.enabled === enabled) action.enabled = previous; });
                    agentChanged = true;
                }
            }
            for (const [config_name, value] of Object.entries(config)) {
                const field = action.config?.[config_name];
                if (!field) continue;
                if (this.isConfigOverridden(agent, action_name, config_name)) {
                    overrideSlice().config[config_name] = { value };
                } else if (field.value !== value) {
                    const previous = field.value;
                    field.value = value;
                    restores.push(() => { if (field.value === value) field.value = previous; });
                    agentChanged = true;
                }
            }
            const answer = replyAfterAll(reply, (slice ? 1 : 0) + (agentChanged ? 1 : 0));
            if (slice) this.saveSceneOverrideSlice(agent, action_name, slice, answer);
            if (agentChanged) this.saveAgent(agent, {
                onComplete: () => answer?.onComplete(),
                // the field objects are shared with every agent status reader: a
                // refused save stored nothing, so its values go back; a failed
                // apply stored them
                onError: (message, applyFailed = false) => {
                    if (!applyFailed) restores.forEach((restore) => restore());
                    answer?.onError(message, applyFailed);
                },
            });
            return true;
        },
        // A stop for a mode the loaded scene is about to be in: a story created
        // from the New Story dialog (armed once it has loaded) or a story-mode
        // switch. It is written when the scene reports the target mode and the
        // three knowledge agents have reported since, refused when the change is
        // rejected, and dropped unwritten after PENDING_EFFORT_TTL. `scope`
        // 'scene' sends it through the scene-only hub writer; the other hosts
        // keep the mixed-scope writer they had.
        queueEffort(stop, mode, { afterLoad = false, scope = null } = {}) {
            this.pendingEffort = {
                stop,
                mode,
                scope,
                // A hub stop belongs to the scene it was queued in; the
                // generation it was composed for travels with it so a load can
                // never apply it to the next scene.
                sceneIdentity: scope === 'scene' ? sceneIdentityOf(this.scene) : null,
                armed: !afterLoad,
                seen: new Set(),
                // a New Story stop starts its clock when the load arms it
                until: afterLoad ? null : Date.now() + PENDING_EFFORT_TTL,
            };
        },
        applyPendingEffort() {
            const pending = this.pendingEffort;
            if (!pending) return;
            if (pending.until !== null && Date.now() > pending.until) {
                this.pendingEffort = null;
                return;
            }
            if (!pending.armed || this.sceneMode !== pending.mode) return;
            if (pending.sceneIdentity && pending.sceneIdentity !== sceneIdentityOf(this.scene)) {
                // the scene changed under a hub stop: drop it, never replay it
                this.pendingEffort = null;
                return;
            }
            if (!EFFORT_AGENTS.every((name) => pending.seen.has(name))) return;
            this.pendingEffort = null;
            if (pending.scope === 'scene') {
                this.applySceneAgentValues(effortPinPatch(this.state.agents, pending.mode, pending.stop));
                return;
            }
            for (const entry of effortPatch(this.state.agents, pending.mode, pending.stop)) {
                const agent = this.state.agents.find((candidate) => candidate.name === entry.agent);
                this.applyActionValues(agent, entry.action, entry);
            }
        },
        // Transport teardown / unmount: drop the hub writer's queued and
        // in-flight work and any stop still waiting for a scene to report.
        resetSceneAgentOverrides() {
            this.overrides?.reset(
                'The connection closed before the change was sent.',
                'The connection closed before the answer arrived; the change may have been saved.',
            );
            this.pendingEffort = null;
            // no answer can arrive now; the statuses of the next connection are the truth
            for (const [requestId, { reply, release }] of Object.entries(this.sliceReplies)) {
                delete this.sliceReplies[requestId];
                release();
                reply?.onError('The connection closed before the answer arrived; the change may have been saved.');
            }
        },
        getQuickToggleActions(agent) {
            const result = {};
            if (agent.actions) {
                for (const action_name in agent.actions) {
                    if (agent.actions[action_name] && agent.actions[action_name].quick_toggle) {
                        result[action_name] = agent.actions[action_name];
                    }
                }
            }
            return result;
        },
        getRootQuickToggleConfigs(action) {
            const result = {};
            for (const config_name in action.config || {}) {
                if (action.config[config_name]?.quick_toggle_root) {
                    result[config_name] = action.config[config_name];
                }
            }
            return result;
        },
        getQuickToggleSubConfigs(action) {
            const result = {};
            if (action.config) {
                for (const config_name in action.config) {
                    if (action.config[config_name] && action.config[config_name].quick_toggle) {
                        result[config_name] = action.config[config_name];
                    }
                }
            }
            return result;
        },
        getActive() {
            return this.state.agents.find(a => a.status === 'busy');
        },
        saveAgent(agent, reply = null) {
            const index = this.state.agents.findIndex(c => c.name === agent.name);
            if (index === -1) {
                this.state.agents.push(agent);
            } else {
                this.state.agents[index] = agent;
            }
            const pending = (this.pendingWrites[agent.name] || []).map((write) => write.held);
            const release = this.holdWrite(agent.name, writtenValues(expectedValues(this.lastReported[agent.name], pending), agent));
            this.$emit('agents-updated', this.state.agents, {
                onComplete: () => {
                    release();
                    reply?.onComplete?.();
                },
                // a failed apply stored the payload, so there is nothing to restore
                onError: (message, applyFailed = false) => {
                    release(!applyFailed);
                    reply?.onError?.(message, applyFailed);
                },
            });
        },
        openMessages(agentName) {
            if(!this.agentMessagesRefs[agentName]) {
                return;
            }
            this.agentMessagesRefs[agentName].openDialog();
        },
        handleMessage(data) {
            // The scene-only writer tracks its own requests and scene generation
            this.overrides?.handleMessage(data);

            if (data.type === 'agent_config' && data.action === 'operation_done' && this.sliceReplies[data.request_id]) {
                const { reply, release } = this.sliceReplies[data.request_id];
                delete this.sliceReplies[data.request_id];
                release(!!data.error);
                if (data.error) reply?.onError(data.error.message);
                else reply?.onComplete();
            }

            // When a new scene is loaded, clear the messages and agentHasMessages
            if (data.type === "system" && data.id === 'scene.loaded') {
                this.messages = {};
                this.agentHasMessages = {};
                // a hub stop belongs to the scene it was queued in: a load is a
                // different scene, so it is dropped rather than re-armed
                if (this.pendingEffort?.scope === 'scene') {
                    this.pendingEffort = null;
                } else if (this.pendingEffort) {
                    // the agents report after this frame; frames from the load itself do not count
                    this.pendingEffort.armed = true;
                    this.pendingEffort.seen = new Set();
                    this.pendingEffort.until = Date.now() + PENDING_EFFORT_TTL;
                }
            }
            if (data.type === "system" && data.id === 'scene.load_failure') {
                this.pendingEffort = null;
            }
            if (data.type === 'scene_status') {
                this.sceneMode = effortMode(perspectivesEnabled(data.data));
                this.applyPendingEffort();
            }
            if (data.type === 'world_state_manager' && data.action === 'operation_done'
                && data.error && data.failed_action === 'update_scene_settings') {
                this.pendingEffort = null;
            }

            // Handle agent_status message type
            if (data.type === 'agent_status') {
                // Find the client with the given name
                const agent = this.state.agents.find(agent => agent.name === data.name);
                if (agent) {

                    // Update the model name of the client
                    agent.client = data.client;
                    agent.data = data.data;
                    agent.status = data.status;
                    agent.label = data.message;
                    agent.meta = data.meta;
                    agent.actions = {}
                    for(let i in data.data.actions) {
                        agent.actions[i] = {...data.data.actions[i]};
                    }
                    agent.enabled = data.data.enabled;

                    // sort agents by label

                    this.state.agents.sort((a, b) => {
                        if(a.label < b.label) { return -1; }
                        if(a.label > b.label) { return 1; }
                        return 0;
                    });

                } else {
                    // Add the agent to the list of agents
                    let actions = {}
                    for(let i in data.data.actions) {
                        //actions[i] = {enabled: data.data.actions[i].enabled, config: data.data.actions[i].config, condition: data.data.actions[i].condition};
                        actions[i] = {...data.data.actions[i]};
                    }
                    this.state.agents.push({
                        name: data.name,
                        client: data.client,
                        status: data.status,
                        data: data.data,
                        label: data.message,
                        actions: actions,
                        enabled: data.data.enabled,
                        meta: data.meta,
                    });
                }
                this.lastReported[data.name] = reportedValues(data.data);
                this.reapplyPendingWrites(this.state.agents.find((candidate) => candidate.name === data.name));
                if (this.pendingEffort?.armed) {
                    this.pendingEffort.seen.add(data.name);
                    this.applyPendingEffort();
                }
                return;
            }

            if (data.type === 'agent_message') {
                const agent = data.data.agent;
                if (!this.messages[agent]) {
                    this.messages[agent] = [];
                }
                this.messages[agent].unshift(data);
                while (this.messages[agent].length > this.maxMessagesPerAgent) {
                    this.messages[agent].pop();
                }
                // set to current time in milliseconds
                this.agentHasMessages[agent] = Date.now();
            }
        }
    },
    created() {
        this.overrides = new SceneAgentOverridesCoordinator({
            getWebsocket: () => this.getWebsocket(),
            scene: () => this.scene,
            state: this.overridesState,
            requestSave: () => this.requestSceneSave(),
        });
        this.registerMessageHandler(this.handleMessage);
    },
    beforeUnmount() {
        this.unregisterMessageHandler(this.handleMessage);
        this.resetSceneAgentOverrides();
    },
}
</script>

<style scoped>
.chip-wrapper {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    max-width: 100%;
    margin-top: 4px;
}

.chip-container {
    gap: 4px;
}
</style>

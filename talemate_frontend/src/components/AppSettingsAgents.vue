<template>
    <v-row>
        <v-col cols="4">
            <v-alert v-if="agents.length === 0" color="muted" variant="text" density="compact" icon="mdi-information-outline" class="mb-2">
                Waiting for agent status.
            </v-alert>
            <v-list slim selectable mandatory v-model:selected="selected" color="primary" density="compact">
                <v-list-item v-for="agent in agents" :key="agent.name" :value="agent.name" :data-setting-anchor="`agent-${agent.name}`">
                    <template v-slot:prepend>
                        <v-progress-circular v-if="isBusy(agent)" indeterminate="disable-shrink" :color="agent.status === 'busy_bg' ? 'secondary' : 'primary'" size="14" class="mr-3"></v-progress-circular>
                        <v-icon v-else :color="statusColor(agent)" size="14" class="mr-3">mdi-checkbox-blank-circle</v-icon>
                    </template>
                    <v-list-item-title>
                        {{ agent.label || agent.name }}
                        <v-tooltip v-if="agent.data.experimental" text="Experimental" density="compact">
                            <template v-slot:activator="{ props }">
                                <v-icon v-bind="props" color="warning" size="14" class="ml-1">mdi-flask-outline</v-icon>
                            </template>
                        </v-tooltip>
                    </v-list-item-title>
                    <v-list-item-subtitle class="text-caption">
                        <span v-if="clientHint(agent)">{{ clientHint(agent) }}</span>
                        <span v-else-if="!agent.data.requires_llm_client" class="text-muted">No LLM client needed</span>
                        <span v-else class="text-muted">No client assigned</span>
                    </v-list-item-subtitle>
                    <template v-slot:append>
                        <v-tooltip v-if="agent.meta && agent.meta.essential === false" text="Optional — Talemate runs without it" density="compact">
                            <template v-slot:activator="{ props }">
                                <v-icon v-bind="props" color="muted" size="14">mdi-circle-outline</v-icon>
                            </template>
                        </v-tooltip>
                    </template>
                </v-list-item>
            </v-list>
        </v-col>

        <v-col cols="8">
            <div v-if="selectedAgent">
                <div class="d-flex align-center mb-2">
                    <v-icon class="mr-2" color="primary">mdi-transit-connection-variant</v-icon>
                    <span class="text-subtitle-1">{{ selectedAgent.label || selectedAgent.name }}</span>
                    <v-spacer></v-spacer>
                    <v-btn-toggle v-if="hasAnyOverridable" :model-value="mode" @update:modelValue="(v) => v && setMode(v)"
                        mandatory density="compact" variant="outlined" color="primary" divided class="mr-4">
                        <v-btn value="global" size="small" prepend-icon="mdi-earth">Global</v-btn>
                        <v-btn value="scene" size="small" prepend-icon="mdi-movie-open-outline">
                            Scene
                            <v-chip v-if="sceneOverrideCount > 0" size="x-small" color="primary" variant="flat" class="ml-2">{{ sceneOverrideCount }}</v-chip>
                        </v-btn>
                    </v-btn-toggle>
                    <v-checkbox v-if="selectedAgent.data.has_toggle && mode === 'global'" :label="agentEnabled(selectedName) ? 'Enabled' : 'Enable'"
                        :model-value="agentEnabled(selectedName)" @update:modelValue="(v) => setAgentEnabled(!!v)"
                        hide-details density="compact" color="green"></v-checkbox>
                </div>

                <template v-if="mode === 'scene'">
                    <v-alert density="compact" variant="tonal" color="primary" class="mb-2" icon="mdi-movie-open-cog-outline">
                        <div class="text-caption">
                            <template v-if="sceneSettingsFile">
                                Scene overrides stored in
                                <code v-if="sceneProjectName">{{ sceneProjectName }}/{{ sceneSettingsDirname }}/{{ sceneSettingsFile }}</code>
                                <code v-else>{{ sceneSettingsDirname }}/{{ sceneSettingsFile }}</code>
                            </template>
                            <template v-else>
                                This scene has no agent-settings file yet — saving your first override creates one.
                            </template>
                        </div>
                    </v-alert>
                    <div class="text-caption text-muted mb-3">
                        <v-icon size="x-small" class="mr-1">mdi-gesture-tap-button</v-icon>
                        Click <v-icon size="x-small" class="mx-1">mdi-link-variant-off</v-icon> next to a field to activate an override for this scene.
                        Overrides are applied when you save.
                    </div>
                </template>

                <v-alert v-if="selectedAgent.data.experimental" type="warning" variant="text" density="compact" icon="mdi-flask-outline" class="mb-2">
                    <span class="text-caption">
                        This agent is currently experimental and may significantly decrease performance and / or require
                        strong LLMs to function properly.
                    </span>
                </v-alert>

                <v-expansion-panels v-model="openPanels" variant="accordion" multiple>
                    <v-expansion-panel v-for="section in sections" :key="section.key" :value="section.key"
                        :data-agent-section="section.key">
                        <v-expansion-panel-title :class="section.parentKey ? 'pl-8' : ''">
                            <v-icon class="mr-2" color="primary" size="small">{{ section.parentKey ? 'mdi-subdirectory-arrow-right' : (section.icon || 'mdi-cog-outline') }}</v-icon>
                            {{ section.label }}
                            <v-chip v-if="section.subtitle" class="ml-2" size="x-small" variant="tonal" label color="secondary">{{ section.subtitle }}</v-chip>
                        </v-expansion-panel-title>
                        <v-expansion-panel-text>
                            <!-- GENERAL — client assignment (global only) and every
                                 non-container action, rendered by the mode's renderer -->
                            <template v-if="section.key === '_config'">
                                <v-select v-if="selectedAgent.data.requires_llm_client && mode === 'global'" :model-value="agentClient(selectedName)"
                                    @update:modelValue="setAgentClient" :items="clientChoices"
                                    label="Client" density="compact"
                                    messages="The LLM client this agent generates with."></v-select>
                                <template v-for="key in inlineActionKeys" :key="key">
                                    <AgentConfigSection v-if="mode === 'global'" v-bind="sectionProps(key)" />
                                    <AgentSceneSettings v-else v-bind="sceneSectionProps(key)" />
                                </template>
                            </template>

                            <!-- DYNAMIC REGISTRY — child management is an immediate RPC, the
                                 registry action itself carries no user-facing fields -->
                            <component
                                v-else-if="section.registry && mode === 'global'"
                                :is="section.registry"
                                :children="dynamicChildren(section.key)"
                                :description="section.description"
                                @add="onAddDynamicChild(section.key, $event)"
                                @remove="onRemoveDynamicChild(section.key, $event)"
                                @rename="(...args) => onRenameDynamicChild(section.key, ...args)"
                                @refresh-voices="onRefreshBackendVoices"
                                :actions-disabled="dirty"
                                actions-disabled-reason="Save your changes first — this runs against the saved configuration."
                            />

                            <AgentConfigSection v-else-if="mode === 'global' && !section.registry" v-bind="sectionProps(section.key)" />

                            <!-- scene mode has no registry management: adding or removing
                                 a backend is global configuration, not a per-scene value -->
                            <AgentSceneSettings v-else-if="mode === 'scene'" v-bind="sceneSectionProps(section.key)" />
                        </v-expansion-panel-text>
                    </v-expansion-panel>
                </v-expansion-panels>
            </div>
            <v-alert v-else color="grey" variant="text">Select an agent to configure</v-alert>
        </v-col>
    </v-row>

    <RequestInput
        ref="namingDialog"
        title="Name scene overrides file"
        icon="mdi-file-cog-outline"
        :placeholder="defaultSettingsFilename"
        :instructions="namingInstructions"
        :rules="filenameRules"
        @continue="onNamingConfirm"
        @cancel="onNamingCancel"
    />
</template>

<script>
import { agentActionConditionMet } from '@/utils/uxConditions';
import AgentConfigSection from './AgentConfigSection.vue';
import AgentSceneSettings from './AgentSceneSettings.vue';
import DynamicAgentRegistry from './DynamicAgentRegistry.vue';
import RequestInput from './RequestInput.vue';
import TTSOpenAICompatibleBackends from './TTSOpenAICompatibleBackends.vue';
import {
    DEFAULT_SCENE_AGENT_SETTINGS_FILENAME,
    SCENE_AGENT_SETTINGS_DIRNAME,
    SCENE_AGENT_SETTINGS_FILENAME_RULES,
    actionHasOverridable,
    countSceneOverrides,
    effectiveConditionMet,
    normalizeSceneOverlay,
    serializeSceneOverlay,
    setActionOverrideSlice,
} from '@/constants/sceneAgentSettings';

// Mapping from `AgentAction.dynamic_registry_component` to the component that
// renders that registry.
const REGISTRY_COMPONENTS = {
    TTSOpenAICompatibleBackends,
};

// Agents page — master / detail configuration of `config.agents` in the app
// settings working copy. Three layers, deliberately kept apart:
//
//   * SCHEMA (labels, field types, conditions, tools, registry children) is
//     live `agent_status` and must never end up in the working copy;
//   * VALUES are read from `config.agents[agent_type]`, falling back to the
//     schema's current value at read time — nothing is written until an edit,
//     which materializes the agent's full persisted entry ({enabled, client,
//     actions}) so an untouched agent never fabricates dirty state;
//   * SCENE OVERRIDES do not live in the app config at all — they buffer here
//     and reach the scene's agent-settings file through the extra-changes
//     contract, so one toolbar Save commits both (config first, slices after).
export default {
    name: 'AppSettingsAgents',
    components: {
        AgentConfigSection,
        AgentSceneSettings,
        DynamicAgentRegistry,
        RequestInput,
        TTSOpenAICompatibleBackends,
    },
    props: {
        config: Object,
        // the host's unsaved-changes state. Actions that run against the
        // APPLIED config (Refresh voices) are disabled while it is set: the
        // edited values exist only in the working copy, so the backend would
        // answer for the values the user just replaced.
        dirty: { type: Boolean, default: false },
    },
    emits: ['extra-dirty', 'extra-error'],
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'getAgents', 'requestTemplates', 'scene', 'isConnected'],
    data() {
        return {
            selected: [],
            // agent_type -> last known agent_status ({name, label, client,
            // status, meta, data}). Never written to the working copy.
            liveAgents: {},
            openPanels: ['_config'],
            // agent types whose full entry has been materialized into the
            // working copy during this editing session
            materialized: {},
            // 'global' = config.agents, 'scene' = the loaded scene's overlay
            mode: 'global',
            templates: {},
            // agent_type -> buffered sparse overlay {actions: {...}}, seeded
            // from the agent's live scene_overrides on first edit. Buffered
            // (not sent) until the toolbar Save commits it.
            sceneOverrideBuffer: {},
            // agent_type -> the overlay the buffer was seeded from. Anything
            // else writing to the same file (quick-toggle chips, the modal,
            // the world editor) is detected by comparing it against live.
            sceneOverrideSeed: {},
            // agent types whose committed slice hasn't been answered yet
            committingAgents: {},
            // request id -> {kind: 'registry' | 'commit', agentType} for our
            // own outstanding `agent_config` requests. The router is shared
            // with the drawer and the world editor, so an operation_done is
            // ours only when it echoes an id we sent.
            pendingOps: {},
            opSeq: 0,
            // agent types whose registry answer died with the connection —
            // the repair it carried is done from the next app_config instead
            // (see dropPendingOps)
            registryRepairs: {},
            // agent_type -> entry of the most recent `app_config` broadcast.
            // A registry op is answered before its agent_status arrives, so
            // this is the only post-op truth the answer can repair the working
            // copy from (see adoptRegistryOp).
            persistedAgents: {},
            // filename picked in the naming prompt for a scene that has no
            // agent-settings file linked yet; sent with the first slice
            pendingFilename: null,
        }
    },
    computed: {
        agents() {
            // same ordering the agent drawer uses — by label
            return Object.values(this.liveAgents).sort((a, b) => (a.label || a.name).localeCompare(b.label || b.name));
        },
        selectedName() {
            return this.selected.length ? this.selected[0] : null;
        },
        selectedAgent() {
            return this.selectedName ? (this.liveAgents[this.selectedName] || null) : null;
        },
        // effective (working copy over live) action values of the selected
        // agent — the read side of every field on the page and the context
        // conditions resolve against
        effectiveActions() {
            return this.effectiveActionsFor(this.selectedName);
        },
        schemaActions() {
            return this.selectedAgent?.data?.actions || {};
        },
        // schema ⊕ effective values, the single-object action shape the
        // scene-mode renderer and the shared override helpers expect (they
        // read structural flags like can_be_disabled alongside values)
        mergedActions() {
            const merged = {};
            for (const [key, schema] of Object.entries(this.schemaActions)) {
                const values = this.effectiveActions[key] || {};
                const config = {};
                for (const [configKey, field] of Object.entries(schema.config || {})) {
                    config[configKey] = { ...field, value: values.config?.[configKey]?.value };
                }
                merged[key] = { ...schema, enabled: values.enabled, config: config };
            }
            return merged;
        },

        // ---- scene state (from the scene status payload) -------------------
        sceneData() {
            return (typeof this.scene === 'function' ? this.scene() : null)?.data || null;
        },
        // a real, saved scene — the placeholder scene has neither, and an
        // overlay written against it would land outside a project folder
        sceneActive() {
            return !!(this.sceneData?.filename && this.sceneData?.project_name);
        },
        sceneOptedOut() {
            return !!this.sceneData?.agent_settings_opted_out;
        },
        sceneSettingsFile() {
            return this.sceneData?.agent_settings_file || null;
        },
        sceneProjectName() {
            return this.sceneData?.project_name || null;
        },
        sceneSettingsDirname() {
            return SCENE_AGENT_SETTINGS_DIRNAME;
        },
        defaultSettingsFilename() {
            return DEFAULT_SCENE_AGENT_SETTINGS_FILENAME;
        },
        filenameRules() {
            return SCENE_AGENT_SETTINGS_FILENAME_RULES;
        },
        namingInstructions() {
            return (
                "No agent-settings file is linked to this scene yet.\n" +
                `Pick a name (must end in .json) for the new file. It'll be saved into the ` +
                `${SCENE_AGENT_SETTINGS_DIRNAME}/ folder of this scene's project. Using the ` +
                "default name lets other scenes in this project auto-link to it."
            );
        },
        // identity of the scene the buffered overlays belong to. Overlay files
        // live in the project folder and are shared by every scene file in it,
        // so the project is what the buffer is tied to — switching save files
        // within one project keeps the overrides valid.
        sceneKey() {
            return this.sceneActive ? this.sceneProjectName : null;
        },
        // a scene that opted out of agent-settings overlays ignores them at
        // runtime, so editing overrides there would be writing into a void
        sceneOverridesAvailable() {
            return this.sceneActive && !this.sceneOptedOut;
        },

        // ---- scene overrides of the selected agent -------------------------
        sceneOverlay() {
            return this.sceneOverlayFor(this.selectedName);
        },
        sceneOverrideCount() {
            return countSceneOverrides(this.sceneOverlay);
        },
        hasAnyOverridable() {
            if (!this.sceneOverridesAvailable) {
                return false;
            }
            for (const key in this.schemaActions) {
                if (actionHasOverridable(this.schemaActions[key], this.sceneConditionCtx(key))) {
                    return true;
                }
            }
            return false;
        },
        generalHasOverridable() {
            // the General section hosts the non-container actions — in scene
            // mode it only exists when one of them has an overridable surface
            for (const key in this.schemaActions) {
                if (this.schemaActions[key].container) continue;
                if (actionHasOverridable(this.schemaActions[key], this.sceneConditionCtx(key))) {
                    return true;
                }
            }
            return false;
        },
        // agent types whose buffered overlay differs from what the scene
        // currently has stored — the payloads Save has to send
        pendingSceneAgents() {
            return Object.keys(this.sceneOverrideBuffer).filter((agentType) => {
                const live = normalizeSceneOverlay(this.liveAgents[agentType]?.data?.scene_overrides);
                return serializeSceneOverlay(this.sceneOverrideBuffer[agentType]) !== serializeSceneOverlay(live);
            });
        },
        hasPendingSceneOverrides() {
            return this.pendingSceneAgents.length > 0;
        },
        // a committed slice is still waiting for its answer — sending another
        // one on top would race the echo we reconcile against
        commitInFlight() {
            return Object.keys(this.committingAgents).length > 0;
        },
        // a registry op has been sent but not answered — until it is, the
        // working copy still carries the pre-op membership, and saving it
        // would undo the op (validate() refuses the save meanwhile)
        registryOpInFlight() {
            return Object.values(this.pendingOps).some(op => op.kind === 'registry');
        },
        // the host's connection state — an answer this page is waiting for
        // cannot outlive the socket it was sent on
        connected() {
            return this.isConnected();
        },
        // Assignable clients come from the working copy, not from the live
        // `data.client` choices — a client added or renamed on the Clients
        // page this session is assignable right away, and one removed there
        // stops being offered, without an intermediate save. A stored
        // assignment the working copy no longer knows is kept in the list so
        // the select doesn't silently blank it out (validate() reports it).
        clientChoices() {
            const names = Object.entries(this.config?.clients || {})
                .filter(([, client]) => client.enabled !== false)
                .map(([name]) => name)
                .sort((a, b) => a.localeCompare(b));
            const assigned = this.agentClient(this.selectedName);
            if (assigned && !names.includes(assigned)) {
                names.unshift(assigned);
            }
            return names;
        },
        inlineActionKeys() {
            // General hosts the `_config` action first, then every other
            // non-container action.
            // In scene mode, actions with nothing overridable are dropped
            // instead of rendering an empty placeholder.
            const include = (key) => this.mode !== 'scene' || actionHasOverridable(this.schemaActions[key], this.sceneConditionCtx(key));
            const keys = [];
            if (this.schemaActions['_config'] && include('_config')) {
                keys.push('_config');
            }
            for (const key in this.schemaActions) {
                if (key !== '_config' && !this.schemaActions[key].container && include(key)) {
                    keys.push(key);
                }
            }
            return keys;
        },
        sections() {
            // General first, then one section per container action whose
            // condition is met, with dynamic children nested under their
            // parent. Scene mode
            // keeps only what it can actually override.
            const sections = [];
            if (this.mode !== 'scene' || this.generalHasOverridable) {
                sections.push({ key: '_config', label: 'General', icon: 'mdi-cog', parentKey: null, registry: null });
            }
            const childrenByParent = {};
            for (const key in this.schemaActions) {
                const schema = this.schemaActions[key];
                if (!schema.container) continue;
                if (!this.actionConditionMet(schema)) continue;
                if (this.mode === 'scene' && !actionHasOverridable(schema, this.sceneConditionCtx(key))) continue;
                const section = {
                    key: key,
                    label: schema.label,
                    icon: schema.icon,
                    subtitle: schema.subtitle,
                    description: schema.description,
                    parentKey: schema.parent_key || null,
                    registry: this.registryComponent(key),
                };
                if (section.parentKey) {
                    if (!childrenByParent[section.parentKey]) childrenByParent[section.parentKey] = [];
                    childrenByParent[section.parentKey].push(section);
                    continue;
                }
                sections.push(section);
            }
            const result = [];
            for (const section of sections) {
                result.push(section);
                for (const child of (childrenByParent[section.key] || [])) {
                    result.push(child);
                }
            }
            return result;
        },
    },
    watch: {
        agents: {
            immediate: true,
            handler(agents) {
                if (this.selectedName && agents.some(agent => agent.name === this.selectedName)) {
                    return;
                }
                this.selected = agents.length ? [agents[0].name] : [];
            },
        },
        config() {
            // the host swaps the working copy object on adopt (save, discard,
            // external change) — entries materialized against the previous
            // copy say nothing about the new one
            this.materialized = {};
        },
        selectedName() {
            this.openPanels = ['_config'];
            if (this.mode === 'scene' && !this.hasAnyOverridable) {
                // the newly selected agent has nothing to override — don't
                // leave the user staring at an empty pane
                this.mode = 'global';
            }
            // `_config` may not be one of this agent's sections (scene mode
            // drops General when no inline action is overridable) — the panel
            // list would render fully collapsed
            this.snapOpenPanels();
        },
        sceneOverridesAvailable(available) {
            if (!available && this.mode === 'scene') {
                this.mode = 'global';
            }
        },
        sceneKey(next, previous) {
            if (next === previous) {
                return;
            }
            // buffered overlays belong to the scene they were edited against;
            // a different (or unloaded) scene can't receive them
            const dropped = Object.keys(this.sceneOverrideBuffer).length > 0;
            this.sceneOverrideBuffer = {};
            this.sceneOverrideSeed = {};
            this.committingAgents = {};
            // answers to slices committed against the previous scene have
            // nothing left to report on (registry ops are scene-independent)
            for (const [id, op] of Object.entries(this.pendingOps)) {
                if (op.kind === 'commit') {
                    delete this.pendingOps[id];
                }
            }
            this.pendingFilename = null;
            if (dropped) {
                this.$emit('extra-error', 'The scene changed — unsaved scene overrides were discarded.');
            }
        },
        hasPendingSceneOverrides: {
            immediate: true,
            handler(pending) {
                // the host folds this into its dirty state (extra-changes contract)
                this.$emit('extra-dirty', pending);
            },
        },
        connected(isConnected) {
            if (!isConnected) {
                this.dropPendingOps();
            }
        },
    },
    methods: {
        // save-time validation contract of the settings pages
        validate() {
            if (this.registryOpInFlight) {
                // the op is persisted server-side but has not reached the
                // working copy yet — this save would ship the pre-op
                // membership and revert it
                return { valid: false, error: 'An agent change is still saving — try again in a moment.' };
            }
            for (const [agentType, entry] of Object.entries(this.config?.agents || {})) {
                if (!entry || !entry.client) {
                    continue;
                }
                if (!this.config?.clients?.[entry.client]) {
                    const label = this.liveAgents[agentType]?.label || agentType;
                    this.selected = [agentType];
                    return { valid: false, error: `${label}: client "${entry.client}" does not exist.` };
                }
            }
            return { valid: true, error: null };
        },

        // what this page shows, folded into the settings view's UX snapshot
        // for the help agent
        uxSnapshot() {
            return { agent: this.selectedName, mode: this.mode };
        },

        // deep link target — `navigate('agents', anchor, {agent, tab, mode})`,
        // where tab is an action key or `_config`
        setSelection(item) {
            const name = typeof item === 'string' ? item : (item?.agent || item?.name);
            if (!name || !this.liveAgents[name]) {
                return;
            }
            this.selected = [name];
            if (typeof item === 'object' && item.mode) {
                // setMode refuses a scene link the agent (or scene) can't honor
                this.setMode(item.mode);
            }
            const section = typeof item === 'object' ? (item.tab || item.section) : null;
            if (!section) {
                return;
            }
            // a link may name an action that has no section of its own (an
            // inline action, or a container whose condition isn't met) —
            // General holds the inline ones, and it beats an all-collapsed pane
            this.openPanels = this.sections.some(s => s.key === section) ? [section] : ['_config'];
            this.snapOpenPanels();
            this.$nextTick(() => {
                const el = this.$el.querySelector(`[data-agent-section="${section}"]`);
                if (el) {
                    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            });
        },

        isBusy(agent) {
            const status = this.agentStatus(agent);
            return status === 'busy' || status === 'busy_bg';
        },

        // The list dot shows the state a save would produce: enabled is
        // working-copy state, everything else (readiness, activity, errors) is
        // live and only describes the agent as it currently runs.
        agentStatus(agent) {
            if (!agent.data?.has_toggle) {
                return agent.status;
            }
            if (!this.agentEnabled(agent.name)) {
                return 'disabled';
            }
            // pending enable — a disabled agent reports nothing else about
            // how it will come up, so it reads as not running yet
            return agent.status === 'disabled' ? 'uninitialized' : agent.status;
        },

        statusColor(agent) {
            switch (this.agentStatus(agent)) {
                case 'uninitialized': return 'orange';
                case 'warning': return 'orange';
                case 'disabled': return 'grey-darken-2';
                case 'error': return 'red-darken-1';
                default: return 'green';
            }
        },

        clientHint(agent) {
            if (!agent.data.requires_llm_client) {
                return null;
            }
            return this.agentClient(agent.name);
        },

        // ------------------------------------------------------------------
        // effective values — working copy first, live schema as fallback
        // ------------------------------------------------------------------

        liveClientName(agent) {
            // agent_status.client is the agent's detail payload: a plain
            // client name for LLM agents, a chip dict for agents that report
            // more (the client name then lives under `client.client.value`)
            const client = agent?.client;
            if (client && typeof client === 'object') {
                return client.client ? client.client.value : null;
            }
            return client || null;
        },

        agentEnabled(agentType) {
            const stored = this.config?.agents?.[agentType];
            if (stored && typeof stored.enabled === 'boolean') {
                return stored.enabled;
            }
            return !!this.liveAgents[agentType]?.data?.enabled;
        },

        agentClient(agentType) {
            const stored = this.config?.agents?.[agentType];
            if (stored && stored.client) {
                return stored.client;
            }
            // the running agent's assignment stands in for an unset one, but
            // only while the working copy still has that client — after it is
            // removed here, "unassigned" is the truth (the backend assigns a
            // new one when the save is applied)
            const live = this.liveClientName(this.liveAgents[agentType]);
            return (live && this.config?.clients?.[live]) ? live : null;
        },

        effectiveActionsFor(agentType) {
            const schemaActions = this.liveAgents[agentType]?.data?.actions || {};
            const storedActions = this.config?.agents?.[agentType]?.actions || {};
            const actions = {};
            for (const [key, schema] of Object.entries(schemaActions)) {
                const stored = storedActions[key] || {};
                const config = {};
                for (const [configKey, field] of Object.entries(schema.config || {})) {
                    const storedValue = stored.config?.[configKey]?.value;
                    config[configKey] = { value: storedValue === undefined ? field.value : storedValue };
                }
                actions[key] = {
                    enabled: typeof stored.enabled === 'boolean' ? stored.enabled : schema.enabled,
                    config: config,
                };
            }
            return actions;
        },

        actionConditionMet(schema) {
            if (this.mode === 'scene') {
                // scene mode judges the condition by what the scene runs on,
                // so overriding a gate field reveals its dependents at once
                return effectiveConditionMet(schema.condition, this.mergedActions, this.sceneOverlay);
            }
            return agentActionConditionMet(schema.condition, this.effectiveActions, this.selectedAgent?.client);
        },

        sectionProps(actionKey) {
            return {
                actionKey: actionKey,
                schema: this.schemaActions[actionKey],
                values: this.effectiveActions[actionKey],
                actions: this.effectiveActions,
                agentClient: this.selectedAgent?.client,
                appConfig: this.config,
                templates: this.templates,
                'onUpdate:enabled': (value) => this.setActionEnabled(this.selectedName, actionKey, value),
                'onUpdate:value': (configKey, value) => this.setConfigValue(this.selectedName, actionKey, configKey, value),
            };
        },

        // ------------------------------------------------------------------
        // write path — materialize on first edit, then apply
        // ------------------------------------------------------------------

        // Builds the agent's complete persisted entry from the effective
        // values so a save carries everything the retired agent modal used to
        // send. Called on the first edit of an agent only.
        materialize(agentType) {
            if (this.materialized[agentType]) {
                return this.config.agents[agentType];
            }
            if (!this.config.agents) {
                this.config.agents = {};
            }
            const data = this.liveAgents[agentType]?.data || {};
            const effective = this.effectiveActionsFor(agentType);
            const actions = {};
            for (const [key, values] of Object.entries(effective)) {
                const config = {};
                for (const [configKey, field] of Object.entries(values.config)) {
                    config[configKey] = { value: field.value };
                }
                actions[key] = { enabled: values.enabled, config: config };
            }
            this.config.agents[agentType] = {
                ...(this.config.agents[agentType] || {}),
                enabled: this.agentEnabled(agentType),
                // agents that don't generate never carry a client — same
                // normalization the old save path applied
                client: data.requires_llm_client ? this.agentClient(agentType) : null,
                actions: actions,
            };
            this.materialized[agentType] = true;
            return this.config.agents[agentType];
        },

        entryAction(agentType, actionKey) {
            const entry = this.materialize(agentType);
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
        },

        setAgentEnabled(value) {
            this.materialize(this.selectedName).enabled = value;
        },

        setAgentClient(value) {
            this.materialize(this.selectedName).client = value;
        },

        setActionEnabled(agentType, actionKey, value) {
            this.entryAction(agentType, actionKey).enabled = value;
        },

        setConfigValue(agentType, actionKey, configKey, value) {
            this.entryAction(agentType, actionKey).config[configKey] = { value: value };
        },

        // ------------------------------------------------------------------
        // scene mode — the per-scene overlay
        //
        // The overlay is NOT app config: it lives in the scene's
        // agent-settings file and travels over `agent_config`. Edits buffer
        // per agent (seeded from the agent's live overrides so the full-slice
        // replace the backend performs never drops an override the user
        // didn't touch) and are sent by the toolbar Save.
        // ------------------------------------------------------------------

        setMode(mode) {
            if (mode === 'scene' && !this.hasAnyOverridable) {
                // scene mode was asked for (deep link, or the previous agent
                // was in it) but this agent/scene has nothing to override
                this.mode = 'global';
                return;
            }
            this.mode = mode;
            this.snapOpenPanels();
        },

        // the section list differs per mode and per agent — keep at least one
        // existing panel open instead of rendering an all-collapsed list
        snapOpenPanels() {
            const valid = this.sections.map(section => section.key);
            if (valid.length && !valid.some(key => this.openPanels.includes(key))) {
                this.openPanels = [valid[0]];
            }
        },

        sceneOverlayFor(agentType) {
            if (!agentType) {
                return { actions: {} };
            }
            // the buffer overlays what the agent currently reports, the same
            // way the working copy overlays the live schema — an agent_status
            // refresh must not clobber unsaved edits
            const buffered = this.sceneOverrideBuffer[agentType];
            if (buffered) {
                return buffered;
            }
            return normalizeSceneOverlay(this.liveAgents[agentType]?.data?.scene_overrides);
        },

        sceneConditionCtx(actionKey) {
            return {
                actions: this.mergedActions,
                overlay: this.sceneOverlay,
                overrides: this.sceneOverlay.actions[actionKey],
            };
        },

        sceneSectionProps(actionKey) {
            return {
                action: this.mergedActions[actionKey],
                actionSchema: this.schemaActions[actionKey],
                overrides: this.sceneOverlay.actions[actionKey] || {},
                agentActions: this.mergedActions,
                overlay: this.sceneOverlay,
                templates: this.templates,
                appConfig: this.config,
                // this page holds a working copy, so a unified_api_key field
                // writes into it and the toolbar Save persists it
                deferred: true,
                'onUpdate:overrides': (slice) => this.setSceneOverrideSlice(this.selectedName, actionKey, slice),
            };
        },

        setSceneOverrideSlice(agentType, actionKey, slice) {
            const overlay = this.sceneOverlayFor(agentType);
            if (!this.sceneOverrideBuffer[agentType]) {
                // remember what the scene held when buffering started, so a
                // write from elsewhere can be told apart from our own edits
                this.sceneOverrideSeed[agentType] = normalizeSceneOverlay(overlay);
            }
            this.sceneOverrideBuffer[agentType] = {
                actions: setActionOverrideSlice(overlay.actions, actionKey, slice),
            };
        },

        // ---- extra-changes contract (see AppSettings.saveConfig) -----------

        hasExtraChanges() {
            return this.hasPendingSceneOverrides;
        },

        // Resolves false to abort the save. The only interactive step is
        // naming the scene's agent-settings file the first time an override
        // is stored for it.
        prepareExtraChanges() {
            // a re-entrant save (or a prompt still open from a previous one)
            // must not strand the earlier promise
            this.resolveFilenamePrompt(false);
            if (!this.hasPendingSceneOverrides) {
                return Promise.resolve(true);
            }
            if (this.commitInFlight) {
                // the previous slice hasn't been answered yet; sending another
                // would race the echo the buffer reconciles against
                this.$emit('extra-error', 'Scene overrides are still saving — try again in a moment.');
                return Promise.resolve(false);
            }
            if (!this.sceneOverridesAvailable) {
                this.$emit('extra-error', 'Scene overrides cannot be saved for this scene.');
                return Promise.resolve(false);
            }
            if (this.sceneSettingsFile) {
                this.pendingFilename = null;
                return Promise.resolve(true);
            }
            return new Promise((resolve) => {
                this._filenamePromptResolve = resolve;
                this.$refs.namingDialog.openDialog({ input: DEFAULT_SCENE_AGENT_SETTINGS_FILENAME });
            });
        },

        onNamingConfirm(filename) {
            // RequestInput enforces filenameRules; Continue stays disabled until they pass
            this.pendingFilename = (filename || '').trim();
            this.resolveFilenamePrompt(true);
        },

        onNamingCancel() {
            // cancelling the prompt aborts the whole save — nothing is sent
            // and every edit stays exactly as it was
            this.pendingFilename = null;
            this.resolveFilenamePrompt(false);
        },

        resolveFilenamePrompt(value) {
            const resolve = this._filenamePromptResolve;
            this._filenamePromptResolve = null;
            if (resolve) {
                resolve(value);
            }
        },

        // One full-slice replace per agent with pending changes. The buffer is
        // deliberately NOT cleared here: an accepted save echoes an
        // agent_status carrying the same overrides and the entry retires
        // itself (handleMessage), while a refusal echoes the unchanged ones
        // and the user's edits survive to be retried.
        commitExtraChanges() {
            if (!this.connectionReady()) {
                // the buffer is kept, as on a refusal, so the save can be retried
                this.$emit('extra-error', 'Not connected to the backend — scene overrides were not saved.');
                return;
            }
            let filename = this.sceneSettingsFile ? null : this.pendingFilename;
            for (const agentType of this.pendingSceneAgents) {
                const payload = {
                    type: 'agent_config',
                    action: 'save_scene_overrides',
                    agent_type: agentType,
                    // server-side `_prune_empty` cleans up empties on write
                    override: this.sceneOverlayFor(agentType),
                    request_id: this.trackRequest('commit', agentType),
                };
                if (filename) {
                    // only the first slice links the file; the rest write into it
                    payload.filename = filename;
                    filename = null;
                }
                this.committingAgents[agentType] = true;
                this.getWebsocket().send(JSON.stringify(payload));
            }
            this.pendingFilename = null;
        },

        discardExtraChanges() {
            this.sceneOverrideBuffer = {};
            this.sceneOverrideSeed = {};
            this.pendingFilename = null;
        },

        // ------------------------------------------------------------------
        // dynamic action registries (e.g. TTS OpenAI-compatible backends)
        //
        // These manage the set of child actions rather than their values, and
        // stay immediate RPCs — the backend persists them itself and echoes an
        // agent_status we reconcile against.
        // ------------------------------------------------------------------

        registryComponent(actionKey) {
            const schema = this.schemaActions[actionKey];
            if (!schema?.config?.dynamic_children) {
                return null;
            }
            const declared = schema.dynamic_registry_component;
            return (declared && REGISTRY_COMPONENTS[declared]) ? REGISTRY_COMPONENTS[declared] : DynamicAgentRegistry;
        },

        dynamicChildren(actionKey) {
            return this.parseChildren(this.effectiveActions?.[actionKey]?.config?.dynamic_children?.value);
        },

        // a frame handed to a socket that is not OPEN is discarded silently, so
        // the answer that would retire its pending entry never comes — nothing
        // may be tracked (or sent) until the connection is back
        connectionReady() {
            const websocket = this.getWebsocket();
            return !!websocket && websocket.readyState === WebSocket.OPEN;
        },

        // ids for our own requests on the shared agent_config router, so an
        // answer can be attributed to the request that caused it
        trackRequest(kind, agentType) {
            const id = `agentcfg-${Date.now()}-${++this.opSeq}`;
            this.pendingOps[id] = { kind, agentType };
            return id;
        },

        // The socket is gone, and with it every answer still outstanding on it.
        // Nothing else retires these entries, so they would gate saving
        // (validate, prepareExtraChanges) for the rest of the session.
        //
        // Dropping them loses no state: a registry op is persisted and
        // broadcast before it is answered, and the host re-requests the config
        // when the socket reopens — so the app_config that follows carries the
        // op, and the repair the answer would have done runs off that broadcast
        // instead (registryRepairs). A committed slice is answered by an
        // agent_status, which the backend re-emits for every agent on connect,
        // and its buffer survives a commit either way — a slice that never
        // landed is simply saved again.
        dropPendingOps() {
            for (const [id, op] of Object.entries(this.pendingOps)) {
                if (op.kind === 'registry') {
                    this.registryRepairs[op.agentType] = true;
                }
                delete this.pendingOps[id];
            }
            this.committingAgents = {};
        },

        sendRegistryRequest(action, actionKey, extra) {
            if (!this.connectionReady()) {
                this.$emit('extra-error', 'Not connected to the backend — the change was not sent.');
                return;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'agent_config',
                action: action,
                agent_type: this.selectedName,
                action_key: actionKey,
                request_id: this.trackRequest('registry', this.selectedName),
                ...extra,
            }));
        },
        onAddDynamicChild(actionKey, label) {
            this.sendRegistryRequest('register_child', actionKey, { label });
        },
        onRemoveDynamicChild(actionKey, slug) {
            this.sendRegistryRequest('unregister_child', actionKey, { slug });
        },
        // the generic registry emits (slug, label); the TTS wrapper re-emits
        // them as a single [slug, label] payload — accept both
        onRenameDynamicChild(actionKey, slug, label) {
            if (Array.isArray(slug)) {
                [slug, label] = slug;
            }
            this.sendRegistryRequest('rename_child', actionKey, { slug, label });
        },
        onRefreshBackendVoices(slug) {
            this.getWebsocket().send(JSON.stringify({
                type: 'tts', action: 'refresh_backend_voices', slug: slug,
            }));
        },

        // A registry op changes which child actions exist. Any working copy
        // entry for that agent predates the change — saving it as-is would
        // push the stale registry blob back and undo the add / remove.
        // Reconcile the membership only; field values the user has edited are
        // left alone. Keyed off the entry existing rather than off this
        // session's materialize bookkeeping: a config loaded with the agent
        // already persisted needs the same treatment.
        reconcileDynamicChildren(agentType, schemaActions) {
            const entry = this.config?.agents?.[agentType];
            if (!entry?.actions || !Object.keys(schemaActions).length) {
                // an empty action map means the agent reported no schema (e.g.
                // it is not instantiated) — not an instruction to drop actions
                return;
            }
            // A stored action carries no parent_key (that is schema, not
            // value), so an unregistered child is recognized by the registry
            // whose stored blob still lists it — captured BEFORE the blobs are
            // synced to their new values.
            const parentOfStoredChild = {};
            for (const [key, action] of Object.entries(entry.actions)) {
                for (const child of this.parseChildren(action?.config?.dynamic_children?.value)) {
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
            // only registry children are ours to drop — an action missing from
            // the live schema for any other reason (a build without that
            // feature, a partially reported agent) keeps its stored config
            for (const key of Object.keys(entry.actions)) {
                if (schemaActions[key]) {
                    continue;
                }
                if (registryKeys.has(parentOfStoredChild[key])) {
                    delete entry.actions[key];
                }
            }
        },

        // Repairs the working copy from the config the backend broadcast with
        // a registry op, which is the state the op was persisted into. The
        // live schema is NOT that state yet: the completion is queued
        // directly while agent_status is debounced, so the broadcast is all
        // this answer has to go on.
        adoptRegistryOp(agentType) {
            const persisted = this.persistedAgents[agentType];
            if (!persisted) {
                // no broadcast to build from — fall back to an entry off the
                // (pre-op) schema, which the agent_status that follows still
                // reconciles the membership into
                if (!this.config?.agents?.[agentType]) {
                    this.materialize(agentType);
                }
                return;
            }
            if (!this.config.agents) {
                this.config.agents = {};
            }
            if (!this.config.agents[agentType]) {
                // the working copy has no entry for this agent, so the next
                // Save would ship a config without it and drop the op — give
                // it the persisted one, which already carries the op
                this.config.agents[agentType] = JSON.parse(JSON.stringify(persisted));
                this.materialized[agentType] = true;
                return;
            }
            // an entry that predates the op (loaded with it, or materialized
            // by an edit made while the op was in flight): its registry blob
            // is the pre-op one. The persisted actions carry the new
            // membership in the shape the reconciler reads — a child action
            // added here has no entry of its own until the status lands, which
            // the backend synthesizes from the blob on save either way.
            this.reconcileDynamicChildren(agentType, persisted.actions || {});
        },

        // Every agent_status carries the agent's stored overrides, which is the
        // only feedback the overlay has: it answers our own commit AND reports
        // what anyone else (quick-toggle chips, the agent modal, the world
        // editor) wrote to the same file while we were buffering.
        reconcileSceneOverrides(agentType) {
            const buffered = this.sceneOverrideBuffer[agentType];
            if (!buffered) {
                return;
            }
            const live = normalizeSceneOverlay(this.liveAgents[agentType]?.data?.scene_overrides);
            if (serializeSceneOverlay(buffered) === serializeSceneOverlay(live)) {
                // stored state caught up with the buffer — our commit landed
                // (or someone stored the same thing); stop shadowing the agent
                delete this.sceneOverrideBuffer[agentType];
                delete this.sceneOverrideSeed[agentType];
                return;
            }
            const seed = this.sceneOverrideSeed[agentType] || { actions: {} };
            if (serializeSceneOverlay(seed) === serializeSceneOverlay(live)) {
                // stored state is still what we started from — the difference
                // is just this page's unsaved edits
                return;
            }
            // Somebody else wrote to this agent's overrides. The commit is a
            // full-slice replace, so keeping the buffer as-is would silently
            // revert their write; adopt it for every action the user has not
            // touched and report only what actually collides.
            const merged = { actions: { ...buffered.actions } };
            const conflicts = [];
            const keys = new Set([
                ...Object.keys(live.actions),
                ...Object.keys(seed.actions),
                ...Object.keys(buffered.actions),
            ]);
            for (const key of keys) {
                const liveSlice = this.serializeSlice(live, key);
                if (liveSlice === this.serializeSlice(seed, key)) {
                    continue;
                }
                if (this.serializeSlice(buffered, key) !== this.serializeSlice(seed, key)) {
                    conflicts.push(key);
                    continue;
                }
                if (live.actions[key]) {
                    merged.actions[key] = JSON.parse(JSON.stringify(live.actions[key]));
                } else {
                    delete merged.actions[key];
                }
            }
            this.sceneOverrideBuffer[agentType] = merged;
            this.sceneOverrideSeed[agentType] = live;
            if (conflicts.length) {
                const label = this.liveAgents[agentType]?.label || agentType;
                this.$emit('extra-error', `${label}: scene overrides were changed elsewhere — your unsaved edits are kept and will overwrite them on save.`);
            }
            if (serializeSceneOverlay(merged) === serializeSceneOverlay(live)) {
                delete this.sceneOverrideBuffer[agentType];
                delete this.sceneOverrideSeed[agentType];
            }
        },

        serializeSlice(overlay, actionKey) {
            const slice = overlay?.actions?.[actionKey];
            return slice ? serializeSceneOverlay({ actions: { [actionKey]: slice } }) : '';
        },

        parseChildren(blob) {
            try {
                const parsed = JSON.parse(blob || '[]');
                return Array.isArray(parsed) ? parsed : [];
            } catch (_e) {
                return [];
            }
        },

        handleMessage(message) {
            if (message.type === 'app_config') {
                // the host adopts (or stashes) this — the page only keeps the
                // agent entries, as the state a registry op was persisted into
                this.persistedAgents = message.data?.agents || {};
                // registry answers lost with a dropped connection: the host
                // re-requests the config on reconnect, so this broadcast is the
                // post-op truth their repair was waiting for. An agent absent
                // from it never received the op (the frame died with the socket).
                for (const agentType of Object.keys(this.registryRepairs)) {
                    if (this.persistedAgents[agentType]) {
                        this.adoptRegistryOp(agentType);
                    }
                }
                this.registryRepairs = {};
                return;
            }
            if (message.type === 'agent_status') {
                this.liveAgents[message.name] = {
                    name: message.name,
                    label: message.message,
                    client: message.client,
                    status: message.status,
                    meta: message.meta,
                    data: message.data,
                };
                this.reconcileDynamicChildren(message.name, message.data?.actions || {});
                // every answer to a committed slice — accepted or refused —
                // re-emits the agent's status, so this is where a commit stops
                // being in flight
                delete this.committingAgents[message.name];
                this.reconcileSceneOverrides(message.name);
                return;
            }
            if (message.type === 'agent_config' && message.action === 'operation_done') {
                // the agent_config router is shared with the drawer and the
                // world editor — an answer is ours only when it echoes an id we
                // sent, so neither their failures land in this page's error
                // channel nor ours go unreported
                const ours = this.pendingOps[message.request_id];
                if (!ours) {
                    return;
                }
                delete this.pendingOps[message.request_id];
                if (message.error) {
                    // a refused override save (or registry op) — the buffered
                    // edits stay put so the user can fix and retry
                    this.$emit('extra-error', message.error.message || 'Agent configuration was refused.');
                    // a refusal may never reach the agent_status path (e.g. an
                    // unknown agent type), so clear the flag here too
                    delete this.committingAgents[ours.agentType];
                    return;
                }
                if (ours.kind === 'registry') {
                    // A registry op is persisted server-side and broadcast as
                    // app_config, which the host adopts — unless this view has
                    // unsaved edits, in which case it stashes it and the
                    // working copy keeps the pre-op membership: the next Save
                    // would ship it and undo the op. Repair it from the
                    // broadcast; until this lands, validate() refuses a save.
                    this.adoptRegistryOp(ours.agentType);
                }
                return;
            }
            if (message.type === 'world_state_manager' && message.action === 'templates') {
                this.templates = message.data;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
        // the agent drawer has been collecting status messages since the app
        // connected — adopt what it already knows instead of waiting for the
        // next status broadcast
        for (const agent of this.getAgents()) {
            this.liveAgents[agent.name] = {
                name: agent.name,
                label: agent.label,
                client: agent.client,
                status: agent.status,
                meta: agent.meta,
                data: agent.data,
            };
        }
        // some agent fields (visual styles) render world-state templates
        this.requestTemplates();
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}
</script>

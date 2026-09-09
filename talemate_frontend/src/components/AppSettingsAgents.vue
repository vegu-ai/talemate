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
                    <v-list-item-subtitle class="text-body-small">
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
                    <span class="text-body-large">{{ selectedAgent.label || selectedAgent.name }}</span>
                    <v-spacer></v-spacer>
                    <v-tooltip v-if="selectedAgent.data.requires_llm_client" location="top"
                        :text="`Per-action settings for the ${selectedAgent.label || selectedAgent.name} agent, such as turning reasoning off`">
                        <template #activator="{ props }">
                            <v-btn v-bind="props" size="small" variant="tonal" color="primary" prepend-icon="mdi-tune" class="text-none mr-4"
                                data-testid="agent-settings-overrides-door" @click="openAgentActionOverrides({ agentType: selectedName })">
                                Agent action overrides
                                <v-chip v-if="selectedOverrideCount > 0" size="x-small" label color="primary" variant="flat" class="ml-1">{{ selectedOverrideCount }}</v-chip>
                            </v-btn>
                        </template>
                    </v-tooltip>
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
                        hide-details density="compact" color="success"></v-checkbox>
                </div>

                <template v-if="mode === 'scene'">
                    <v-alert density="compact" variant="tonal" color="primary" class="mb-2" icon="mdi-movie-open-cog-outline">
                        <div class="text-body-small">
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
                    <div class="text-body-small text-muted mb-3">
                        <v-icon size="x-small" class="mr-1">mdi-gesture-tap-button</v-icon>
                        Click <v-icon size="x-small" class="mx-1">mdi-link-variant-off</v-icon> next to a field to activate an override for this scene.
                        Overrides are applied when you save.
                    </div>
                </template>

                <v-alert v-if="selectedAgent.data.experimental" type="warning" variant="text" density="compact" icon="mdi-flask-outline" class="mb-2">
                    <span class="text-body-small">
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

                            <template v-else-if="mode === 'global' && !section.registry">
                                <!-- one stop writes three agents, so the slider is not part of the section -->
                                <KnowledgeEffortSlider v-if="selectedName === 'conversation' && section.key === 'character_knowledge'"
                                    :mode="effortMode" :agents="effortAgents" class="mb-4" @apply="applyEffort" />
                                <AgentConfigSection v-bind="sectionProps(section.key)" />
                            </template>

                            <!-- scene mode has no registry management: adding or removing
                                 a backend is global configuration, not a per-scene value -->
                            <AgentSceneSettings v-else-if="mode === 'scene'" v-bind="sceneSectionProps(section.key)" />
                        </v-expansion-panel-text>
                    </v-expansion-panel>
                </v-expansion-panels>
            </div>
            <v-alert v-else class="text-medium-emphasis" variant="text">Select an agent to configure</v-alert>
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
import { countOverrides } from '@/utils/agentActionOverrides';
import { hasOwnName } from '@/utils/nameKeyedMap';
import AgentConfigSection from './AgentConfigSection.vue';
import AgentSceneSettings from './AgentSceneSettings.vue';
import KnowledgeEffortSlider from './KnowledgeEffortSlider.vue';
import { effortMode, effortPatch } from '@/utils/knowledgeEffort';
import { perspectivesEnabled } from '@/utils/sceneSettings';
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
} from '@/constants/sceneAgentSettings';
import {
    OP_KIND,
    adoptRegistryOp as adoptRegistryOpInto,
    attributeOperation,
    dropPendingOps as forgetPendingOps,
    makeRequestId,
    registryOpInFlight as hasRegistryOpInFlight,
    trackRequest as recordRequest,
} from '@/utils/agentConfigOps';
import {
    mergeSceneOverrides,
    parseDynamicChildren,
    reconcileDynamicChildren as reconcileEntryChildren,
} from '@/utils/agentSettingsReconcile';
import {
    agentClient as readAgentClient,
    agentEnabled as readAgentEnabled,
    effectiveActionsFor as readEffectiveActions,
    entryAction as entryActionSlice,
    materializeAgentEntry,
} from '@/utils/agentSettingsWorkingCopy';
import {
    COMMIT_DECISION,
    bufferOverrideSlice,
    buildCommitPayloads,
    pendingSceneAgents as collectPendingSceneAgents,
    prepareCommitDecision,
    resetForSceneChange,
    sceneOverlayFor as readSceneOverlay,
} from '@/utils/sceneOverrideCommit';

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
        KnowledgeEffortSlider,
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
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'getAgents', 'requestTemplates', 'scene', 'isConnected', 'openAgentActionOverrides'],
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
        selectedOverrideCount() {
            return countOverrides(this.config?.agent_actions?.overrides, this.selectedName);
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
        effortMode() {
            return effortMode(perspectivesEnabled(this.sceneData));
        },
        // the three knowledge agents in agent_status shape, valued from the
        // working copy so the slider reads unsaved edits
        effortAgents() {
            return ['conversation', 'summarizer', 'memory']
                .filter((name) => this.liveAgents[name])
                .map((name) => {
                    const effective = this.effectiveActionsFor(name);
                    const actions = {};
                    for (const [key, action] of Object.entries(this.liveAgents[name].data?.actions || {})) {
                        const config = {};
                        for (const [configKey, field] of Object.entries(action.config || {})) {
                            config[configKey] = { ...field, value: effective[key]?.config?.[configKey]?.value ?? field.value };
                        }
                        actions[key] = { ...action, enabled: effective[key]?.enabled ?? action.enabled, config };
                    }
                    return { name, label: this.liveAgents[name].label, data: { scene_overrides: {} }, actions };
                });
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
            return collectPendingSceneAgents(this.sceneOverrideBuffer, this.liveAgents);
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
            return hasRegistryOpInFlight(this.pendingOps);
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
            const { dropped } = resetForSceneChange({
                buffer: this.sceneOverrideBuffer,
                seed: this.sceneOverrideSeed,
                committingAgents: this.committingAgents,
                pendingOps: this.pendingOps,
            });
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
                if (!hasOwnName(this.config?.clients, entry.client)) {
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
                case 'uninitialized': return 'warning';
                case 'warning': return 'warning';
                case 'disabled': return 'muted';
                case 'error': return 'delete';
                default: return 'success';
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

        agentEnabled(agentType) {
            return readAgentEnabled(this.config, this.liveAgents, agentType);
        },

        agentClient(agentType) {
            return readAgentClient(this.config, this.liveAgents, agentType);
        },

        effectiveActionsFor(agentType) {
            return readEffectiveActions(this.config, this.liveAgents, agentType);
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

        // The agent's full persisted entry, built on the first edit of this
        // session so an untouched agent never fabricates dirty state.
        materialize(agentType) {
            if (this.materialized[agentType]) {
                return this.config.agents[agentType];
            }
            const entry = materializeAgentEntry(this.config, this.liveAgents, agentType);
            this.materialized[agentType] = true;
            return entry;
        },

        entryAction(agentType, actionKey) {
            return entryActionSlice(this.materialize(agentType), actionKey);
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

        applyEffort(stop) {
            for (const entry of effortPatch(this.effortAgents, this.effortMode, stop)) {
                if (entry.enabled !== undefined) this.setActionEnabled(entry.agent, entry.action, entry.enabled);
                for (const [configKey, value] of Object.entries(entry.config)) {
                    this.setConfigValue(entry.agent, entry.action, configKey, value);
                }
            }
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
            return readSceneOverlay({ buffer: this.sceneOverrideBuffer, liveAgents: this.liveAgents }, agentType);
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
                'onUpdate:overrides': (slice) => this.setSceneOverrideSlice(this.selectedName, actionKey, slice),
            };
        },

        setSceneOverrideSlice(agentType, actionKey, slice) {
            bufferOverrideSlice(
                { buffer: this.sceneOverrideBuffer, seed: this.sceneOverrideSeed, liveAgents: this.liveAgents },
                agentType,
                actionKey,
                slice,
            );
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
            const decision = prepareCommitDecision({
                pending: this.hasPendingSceneOverrides,
                commitInFlight: this.commitInFlight,
                overridesAvailable: this.sceneOverridesAvailable,
                settingsFile: this.sceneSettingsFile,
            });
            if (decision === COMMIT_DECISION.NOTHING) {
                return Promise.resolve(true);
            }
            if (decision === COMMIT_DECISION.BLOCKED_COMMIT_IN_FLIGHT) {
                this.$emit('extra-error', 'Scene overrides are still saving — try again in a moment.');
                return Promise.resolve(false);
            }
            if (decision === COMMIT_DECISION.BLOCKED_UNAVAILABLE) {
                this.$emit('extra-error', 'Scene overrides cannot be saved for this scene.');
                return Promise.resolve(false);
            }
            if (decision === COMMIT_DECISION.READY) {
                this.pendingFilename = null;
                return Promise.resolve(true);
            }
            if (decision === COMMIT_DECISION.NEEDS_FILENAME) {
                return new Promise((resolve) => {
                    this._filenamePromptResolve = resolve;
                    this.$refs.namingDialog.openDialog({ input: DEFAULT_SCENE_AGENT_SETTINGS_FILENAME });
                });
            }
            // an unknown token means the module and this chain drifted apart —
            // abort the save rather than let it fall through to a send
            this.$emit('extra-error', `Scene overrides were not saved (unknown save decision "${decision}").`);
            return Promise.resolve(false);
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
            const payloads = buildCommitPayloads({
                agentTypes: this.pendingSceneAgents,
                overlayFor: (agentType) => this.sceneOverlayFor(agentType),
                filename: this.sceneSettingsFile ? null : this.pendingFilename,
                makeId: (agentType) => this.trackRequest(OP_KIND.COMMIT, agentType),
            });
            for (const payload of payloads) {
                this.committingAgents[payload.agent_type] = true;
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
            return parseDynamicChildren(this.effectiveActions?.[actionKey]?.config?.dynamic_children?.value);
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
            const id = makeRequestId(++this.opSeq);
            recordRequest(this.pendingOps, id, kind, agentType);
            return id;
        },

        // The socket is gone, and with it every answer still outstanding on it.
        // Nothing else retires these entries, so they would gate saving
        // (validate, prepareExtraChanges) for the rest of the session.
        dropPendingOps() {
            forgetPendingOps(this.pendingOps, this.registryRepairs);
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
                request_id: this.trackRequest(OP_KIND.REGISTRY, this.selectedName),
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

        // Keyed off the working copy entry existing rather than off this
        // session's materialize bookkeeping: a config loaded with the agent
        // already persisted needs the same treatment.
        reconcileDynamicChildren(agentType, schemaActions) {
            reconcileEntryChildren(this.config?.agents?.[agentType], schemaActions);
        },

        adoptRegistryOp(agentType) {
            const adopted = adoptRegistryOpInto({
                config: this.config,
                agentType: agentType,
                persistedEntry: this.persistedAgents[agentType],
                materialize: () => this.materialize(agentType),
            });
            if (adopted) {
                this.materialized[agentType] = true;
            }
        },

        // Every agent_status carries the agent's stored overrides, which is the
        // only feedback the overlay has: it answers our own commit AND reports
        // what anyone else (quick-toggle chips, the agent modal, the world
        // editor) wrote to the same file while we were buffering.
        reconcileSceneOverrides(agentType) {
            const result = mergeSceneOverrides({
                buffered: this.sceneOverrideBuffer[agentType],
                seed: this.sceneOverrideSeed[agentType],
                live: this.liveAgents[agentType]?.data?.scene_overrides,
            });
            if (result.action === 'merge') {
                this.sceneOverrideBuffer[agentType] = result.merged;
                this.sceneOverrideSeed[agentType] = result.seed;
            } else if (result.action === 'clear') {
                // stop shadowing the agent
                delete this.sceneOverrideBuffer[agentType];
                delete this.sceneOverrideSeed[agentType];
            }
            if (result.conflicts.length) {
                const label = this.liveAgents[agentType]?.label || agentType;
                this.$emit('extra-error', `${label}: scene overrides were changed elsewhere — your unsaved edits are kept and will overwrite them on save.`);
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
                const ours = attributeOperation(this.pendingOps, message.request_id);
                if (!ours) {
                    return;
                }
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

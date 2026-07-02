<template>
  <v-dialog
    :model-value="localDialog"
    @update:model-value="onDialogModelUpdate"
    max-width="1200px"
  >
    <v-card>
      <v-card-title>
        <v-row>
          <v-col cols="4">
            <v-icon>mdi-transit-connection-variant</v-icon>
            {{ agent.label }}
          </v-col>
          <v-col cols="4" class="d-flex align-center justify-center">
            <v-btn-toggle
              v-if="hasAnyOverridable"
              :model-value="mode"
              @update:model-value="(v) => v && setMode(v)"
              mandatory
              density="compact"
              variant="outlined"
              color="primary"
              divided
            >
              <v-btn value="global" size="small" prepend-icon="mdi-earth">Global</v-btn>
              <v-btn value="scene" size="small" prepend-icon="mdi-movie-open-outline">
                Scene
                <v-chip
                  v-if="sceneOverrideCount > 0"
                  size="x-small"
                  color="primary"
                  variant="flat"
                  class="ml-2"
                >{{ sceneOverrideCount }}</v-chip>
              </v-btn>
            </v-btn-toggle>
          </v-col>
          <v-col cols="4" class="text-right checkbox-right">
            <v-checkbox :label="enabledLabel()" hide-details density="compact" color="green" v-model="agent.enabled"
              v-if="agent.data.has_toggle && mode === 'global'" @update:modelValue="save(false)"></v-checkbox>
          </v-col>
        </v-row>
      </v-card-title>

      <v-card-text>
        <v-row>
          <v-col cols="4">
            <v-tabs v-model="tab" color="primary" direction="vertical">
              <v-tab
                v-for="item in tabs"
                :key="item.name"
                v-model="tab"
                :value="item.name"
                :prepend-icon="item.parentKey ? 'mdi-subdirectory-arrow-right' : item.icon"
                :class="item.parentKey ? 'pl-6 text-body-2' : ''"
              >
                <span>{{ item.label }}</span>
                <v-chip class="ml-2" size="x-small" variant="tonal" label color="secondary" v-if="item.action.subtitle">{{ item.action.subtitle }}</v-chip>
              </v-tab>
            </v-tabs>
          </v-col>
          <v-col cols="8" class="scrollable-content">

            <v-alert v-if="mode === 'scene' && sceneSettingsFile" density="compact" variant="tonal" color="primary" class="mb-3" icon="mdi-movie-open-cog-outline">
              <div class="text-caption">
                Scene overrides stored in
                <code v-if="sceneProjectName">{{ sceneProjectName }}/{{ sceneSettingsDirname }}/{{ sceneSettingsFile }}</code>
                <code v-else>{{ sceneSettingsDirname }}/{{ sceneSettingsFile }}</code>
              </div>
            </v-alert>
            <div v-if="mode === 'scene'" class="text-caption text-muted mb-3">
              <v-icon size="x-small" class="mr-1">mdi-gesture-tap-button</v-icon>
              Click <v-icon size="x-small" class="mx-1">mdi-link-variant-off</v-icon> next to a field to activate an override for this scene.
            </div>

            <v-window v-model="tab">
              <v-window-item :value="item.name" v-for="item in tabs" :key="item.name">

                <v-select v-if="agent.data.requires_llm_client && tab === '_config' && mode === 'global'" v-model="selectedClient" :items="agent.data.client" label="Client"  @update:modelValue="save(false)"></v-select>

                <component
                  v-if="tab === item.name && isRegistryTab && agent.data.actions[item.name] && mode === 'global'"
                  :is="resolveRegistryComponent(item.name)"
                  :children="dynamicChildrenForCurrentTab"
                  :description="agent.data.actions[item.name].description"
                  @add="onAddDynamicChild(item.name, $event)"
                  @remove="onRemoveDynamicChild(item.name, $event)"
                  @rename="onRenameDynamicChild(item.name, $event[0], $event[1])"
                  @refresh-voices="onRefreshBackendVoices"
                />

                <template v-for="(action, key) in actionsForTab" :key="key">
                  <AgentGlobalSettings
                    v-if="mode === 'global' && !(isRegistryTab && tab === item.name && key === item.name)"
                    :agent="agent"
                    :action="action"
                    :action-key="key"
                    :action-schema="agent.data.actions[key]"
                    :app-config="appConfig"
                    :templates="templates"
                    @change="save(false)"
                  />
                  <AgentSceneSettings
                    v-else-if="mode === 'scene'"
                    :action="action"
                    :action-schema="agent.data.actions[key]"
                    :app-config="appConfig"
                    :templates="templates"
                    :overrides="sceneOverrides.actions[key] || {}"
                    @update:overrides="(v) => updateActionOverrides(key, v)"
                    @change="dirtyScene = true"
                  />
                </template>

              </v-window-item>
            </v-window>
          </v-col>
        </v-row>

        <v-row>
          <v-col cols="12">
            <v-alert type="warning" variant="outlined" density="compact" v-if="agent.data.experimental">
              <span class="text-caption">
                This agent is currently experimental and may significantly decrease performance and / or require
                strong LLMs to function properly.
              </span>
            </v-alert>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
  </v-dialog>

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
import {getProperty} from 'dot-prop';
import AgentGlobalSettings from './AgentGlobalSettings.vue';
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
} from '@/constants/sceneAgentSettings';

// Mapping from `AgentAction.dynamic_registry_component` (declared by the
// Python agent action) to the Vue component that should render that
// registry's management tab. Anything not in this map (or unset on the
// action) falls back to the generic DynamicAgentRegistry.
const REGISTRY_COMPONENTS = {
  TTSOpenAICompatibleBackends,
};

export default {
  props: {
    dialog: Boolean,
    formTitle: String,
    templates: Object,
    appConfig: Object,
    // Active scene state mirrored from TalemateApp. We only read
    // ``scene.data.project_name`` here — used to render the full overlay
    // path (``<project>/<file>``) in the Scene-mode banner.
    scene: Object,
  },
  components: {
    AgentGlobalSettings,
    AgentSceneSettings,
    DynamicAgentRegistry,
    RequestInput,
    TTSOpenAICompatibleBackends,
  },
  inject: ['state', 'getWebsocket', 'callAgentTool'],
  emits: ['save', 'update:dialog'],
  data() {
    return {
      localDialog: this.state.dialog,
      selectedClient: null,
      tab: "_config",
      // deep clone to avoid mutations being immediately reflected in the source object
      agent: JSON.parse(JSON.stringify(this.state.currentAgent)),
      // 'global' = existing per-agent config; 'scene' = per-scene overlay.
      mode: 'global',
      // Sparse overlay {actions: {<key>: {enabled?, config: {<key>: {value}}}}}
      // — seeded from agent.data.scene_overrides whenever the dialog opens.
      sceneOverrides: { actions: {} },
      // Gates the scene-overrides websocket save on dialog close; only sent
      // when something actually changed in Scene mode.
      dirtyScene: false,
      // Default filename for the agent-settings JSON file when the scene
      // has none linked yet. Editable inline in Scene mode.
      pendingFilename: DEFAULT_SCENE_AGENT_SETTINGS_FILENAME,
    };
  },
  computed: {
    tabs() {
      // Always start with the General (_config) tab in Global mode. In Scene
      // mode, only show it when at least one non-container action (the
      // `_config` AgentAction itself or any other inline action) has a
      // scene-overridable surface — the General tab is where those render.
      // Container actions become tabs; in Scene mode, only those that
      // declare at least one scene_overridable field (or
      // enabled_scene_overridable) get a tab.
      const tabs = [];
      if (this.mode === 'global' || (this.mode === 'scene' && this.generalTabHasOverridable)) {
        tabs.push({ name: "_config", label: "General", icon: "mdi-cog", action: {}, parentKey: null });
      }
      const childrenByParent = {};
      for (const key in this.agent.actions) {
        const action = this.agent.actions[key];
        if (!action.container) continue;
        if (this.testActionConditional(action) === false) continue;
        if (this.mode === 'scene' && !this.containerHasOverridable(key)) continue;

        if (action.parent_key) {
          if (!childrenByParent[action.parent_key]) childrenByParent[action.parent_key] = [];
          childrenByParent[action.parent_key].push({
            name: key, label: action.label, icon: action.icon, action, parentKey: action.parent_key,
          });
          continue;
        }
        tabs.push({ name: key, label: action.label, icon: action.icon, action, parentKey: null });
      }
      const result = [];
      for (const tab of tabs) {
        result.push(tab);
        const children = childrenByParent[tab.name];
        if (children && children.length) for (const child of children) result.push(child);
      }
      return result;
    },

    dynamicChildrenForCurrentTab() {
      const action = this.agent.actions[this.tab];
      if (!action || !action.config || !action.config.dynamic_children) return null;
      try {
        const parsed = JSON.parse(action.config.dynamic_children.value || '[]');
        return Array.isArray(parsed) ? parsed : [];
      } catch (_e) {
        return [];
      }
    },

    isRegistryTab() {
      return this.dynamicChildrenForCurrentTab !== null;
    },

    actionsForTab() {
      // _config: show all non-container actions inline. In Scene mode, drop
      // any non-container action that has no scene-overridable surface so we
      // don't litter the panel with empty "no scene-overridable fields"
      // placeholders.
      // Other tabs: just the one matching action.
      let actions = {};
      if (this.tab === "_config") {
        const include = (key) => this.mode !== 'scene' || this.actionHasOverridableSchema(key);
        if (this.agent.actions["_config"] && include("_config")) {
          actions["_config"] = this.agent.actions["_config"];
        }
        for (let key in this.agent.actions) {
          if (!this.agent.actions[key].container && include(key)) {
            actions[key] = this.agent.actions[key];
          }
        }
      } else if (this.agent.actions[this.tab]) {
        actions[this.tab] = this.agent.actions[this.tab];
      }
      return actions;
    },

    hasAnyOverridable() {
      // Both the schema must have overridable fields AND a real scene must
      // be loaded — otherwise the overlay would have nowhere sane to live
      // on disk (the placeholder Scene has no project_name).
      if (!this.sceneActive) return false;
      const actions = this.agent?.data?.actions || {};
      for (const key in actions) {
        if (actionHasOverridable(actions[key])) return true;
      }
      return false;
    },

    generalTabHasOverridable() {
      // True when at least one non-container action (which renders inline
      // under the General tab) has a scene-overridable surface — gates the
      // Scene-mode General tab.
      const actions = this.agent?.data?.actions || {};
      for (const key in actions) {
        const schema = actions[key];
        if (schema?.container) continue;
        if (actionHasOverridable(schema)) return true;
      }
      return false;
    },

    // Derived from scene_status (carried via the `scene` prop). A real
    // loaded scene has both a filename and a project_name; the websocket
    // handler's placeholder Scene has neither, and saving overrides
    // against it would litter scenes/ root with the overlay file.
    sceneActive() {
      return !!(this.scene?.data?.filename && this.scene?.data?.project_name);
    },

    sceneSettingsFile() {
      return this.scene?.data?.agent_settings_file || null;
    },

    sceneProjectName() {
      return this.scene?.data?.project_name || null;
    },

    // Reads from the local in-memory overlay so it updates as the user
    // toggles, before any websocket round-trip.
    sceneOverrideCount() {
      return countSceneOverrides(this.sceneOverrides);
    },

    namingInstructions() {
      return (
        "No agent-settings file is linked to this scene yet.\n" +
        `Pick a name (must end in .json) for the new file. It'll be saved into the ` +
        `${SCENE_AGENT_SETTINGS_DIRNAME}/ folder of this scene's project. Using the ` +
        "default name lets other scenes in this project auto-link to it."
      );
    },

    filenameRules() {
      return SCENE_AGENT_SETTINGS_FILENAME_RULES;
    },

    defaultSettingsFilename() {
      return DEFAULT_SCENE_AGENT_SETTINGS_FILENAME;
    },

    sceneSettingsDirname() {
      return SCENE_AGENT_SETTINGS_DIRNAME;
    },
  },
  watch: {
    'state.dialog': {
      immediate: true,
      handler(newVal) {
        this.localDialog = newVal;
        if (newVal) {
          this.selectedClient = typeof(this.agent.client) === 'object' && this.agent.client.client ? this.agent.client.client.value : this.agent.client;
        }
      }
    },
    'state.currentAgent': {
      immediate: true,
      handler(newVal) {
        // deep clone whenever a new agent is provided (e.g. opening a different agent)
        this.agent = JSON.parse(JSON.stringify(newVal));
        // Re-seed the scene-overrides overlay from the agent payload.
        const seed = newVal?.data?.scene_overrides || {};
        this.sceneOverrides = {
          actions: seed.actions ? JSON.parse(JSON.stringify(seed.actions)) : {},
        };
        this.dirtyScene = false;
        this.pendingFilename = this.sceneSettingsFile || DEFAULT_SCENE_AGENT_SETTINGS_FILENAME;
        // If we're in scene mode but the new agent has nothing to override,
        // bounce back to global so the user isn't staring at an empty pane.
        if (this.mode === 'scene' && !this.hasAnyOverridable) {
          this.mode = 'global';
        }
      }
    },
    localDialog(newVal) {
      // whenever the dialog closes, persist changes
      if (!newVal) this.finalizeSave();
      this.$emit('update:dialog', newVal);
    }
  },
  methods: {
    enabledLabel() {
      return this.agent.enabled ? 'Enabled' : 'Enable';
    },

    setMode(newMode) {
      if (newMode === 'scene' && !this.hasAnyOverridable) return;
      this.mode = newMode;
      // Snap the active tab to a valid one for the new mode.
      const valid = this.tabs.map(t => t.name);
      if (valid.length && !valid.includes(this.tab)) this.tab = valid[0];
    },

    containerHasOverridable(actionKey) {
      const schema = this.agent?.data?.actions?.[actionKey];
      return !!schema?.container && actionHasOverridable(schema);
    },

    actionHasOverridableSchema(actionKey) {
      const schema = this.agent?.data?.actions?.[actionKey];
      return actionHasOverridable(schema);
    },

    testActionConditional(action) {
      if (action.condition == null) return true;
      if (typeof(this.agent.client) !== 'object') return true;
      let value = getProperty(this.agent.actions, action.condition.attribute + ".value");
      if (Array.isArray(action.condition.value)) {
        return action.condition.value.some(v => v == value);
      }
      return value == action.condition.value;
    },

    close() {
      this.finalizeSave();
      this.$emit('update:dialog', false);
    },

    // Updates the in-memory agent. The actual websocket push happens in
    // finalizeSave (on dialog close).
    save(finalize = false) {
      if (finalize) { this.finalizeSave(); return; }
      if (this.selectedClient != null) {
        if (typeof this.agent.client === 'object') {
          if (this.agent.client.client != null) {
            this.agent.client.client.value = this.selectedClient;
          }
        } else {
          this.agent.client = this.selectedClient;
        }
      }
    },

    finalizeSave() {
      this.save();
      this.$emit('save', this.agent);
      if (this.dirtyScene && this.sceneSettingsFile) {
        // File already linked; push the overrides into the existing file.
        // The unlinked-and-dirty case is handled before the modal closes
        // (see onDialogModelUpdate); by the time finalizeSave runs we
        // either have a filename or dirtyScene has been cleared.
        this.saveSceneOverrides();
      }
    },

    // Intercept close — if scene overrides are dirty and no file is linked,
    // overlay the naming prompt instead of closing.
    onDialogModelUpdate(newVal) {
      if (!newVal && this.dirtyScene && !this.sceneSettingsFile) {
        this.$refs.namingDialog.openDialog({ input: DEFAULT_SCENE_AGENT_SETTINGS_FILENAME });
        return;
      }
      this.localDialog = newVal;
    },

    onNamingConfirm(filename) {
      // RequestInput enforces filenameRules; Continue is disabled until they pass.
      this.pendingFilename = filename.trim();
      this.saveSceneOverrides();
      this.localDialog = false;
    },

    onNamingCancel() {
      // Just dismiss the prompt — leave the modal open and the in-memory
      // overrides intact. The user can keep editing, save with a different
      // name, or trigger another close (which will re-prompt). We don't
      // discard here because the naming prompt may have been triggered by
      // an accidental click-outside, and discarding work on that path is
      // a UX trap.
    },

    // ----------------------------------------------------------------
    // Scene-mode persistence
    // ----------------------------------------------------------------

    updateActionOverrides(actionKey, perActionOverride) {
      // Replace this action's slice. Drop it entirely if empty so the
      // overlay stays sparse.
      const next = { actions: { ...this.sceneOverrides.actions } };
      const isEmpty =
        !perActionOverride ||
        ((perActionOverride.enabled === undefined || perActionOverride.enabled === null) &&
          (!perActionOverride.config || Object.keys(perActionOverride.config).length === 0));
      if (isEmpty) {
        delete next.actions[actionKey];
      } else {
        next.actions[actionKey] = perActionOverride;
      }
      this.sceneOverrides = next;
    },

    saveSceneOverrides() {
      const payload = {
        type: 'agent_config',
        action: 'save_scene_overrides',
        agent_type: this.agent.name,
        // Server-side `SceneAgentSettings._prune_empty` cleans up empties
        // on write, so we ship the raw overlay.
        override: this.sceneOverrides,
      };
      if (!this.sceneSettingsFile && this.pendingFilename) {
        payload.filename = this.pendingFilename;
      }
      this.getWebsocket().send(JSON.stringify(payload));
      this.dirtyScene = false;
    },

    // ----------------------------------------------------------------
    // Dynamic-action registry (e.g., TTS OpenAI-compatible backends)
    // ----------------------------------------------------------------

    onAddDynamicChild(actionKey, label) {
      this.getWebsocket().send(JSON.stringify({
        type: 'agent_config', action: 'register_child',
        agent_type: this.agent.name, action_key: actionKey, label,
      }));
    },
    onRemoveDynamicChild(actionKey, slug) {
      this.getWebsocket().send(JSON.stringify({
        type: 'agent_config', action: 'unregister_child',
        agent_type: this.agent.name, action_key: actionKey, slug,
      }));
    },
    onRenameDynamicChild(actionKey, slug, label) {
      this.getWebsocket().send(JSON.stringify({
        type: 'agent_config', action: 'rename_child',
        agent_type: this.agent.name, action_key: actionKey, slug, label,
      }));
    },
    onRefreshBackendVoices(slug) {
      this.getWebsocket().send(JSON.stringify({
        type: 'tts', action: 'refresh_backend_voices', slug,
      }));
    },
    resolveRegistryComponent(actionKey) {
      const declared = this.agent?.data?.actions?.[actionKey]?.dynamic_registry_component;
      if (declared && REGISTRY_COMPONENTS[declared]) return REGISTRY_COMPONENTS[declared];
      return DynamicAgentRegistry;
    },

    /**
     * Updates only the choices arrays in the local agent object from updated agent data,
     * preserving all user-entered values to avoid overwriting unsaved changes.
     *
     * Also reconciles dynamic-action-registry membership: new children that
     * appeared server-side (via Add Backend) get cloned into the local agent;
     * children removed server-side get dropped; the registry's dynamic_children
     * blob value is synced so a subsequent close-and-save round-trip preserves
     * the new state.
     */
    updateChoicesOnly(updatedAgent) {
      if (!updatedAgent?.data?.actions || !this.agent?.data?.actions) return;
      for (const actionKey in updatedAgent.data.actions) {
        const updatedAction = updatedAgent.data.actions[actionKey];
        if (!updatedAction?.config) continue;
        if (!this.agent.data.actions[actionKey]) this.agent.data.actions[actionKey] = {};
        if (!this.agent.data.actions[actionKey].config) this.agent.data.actions[actionKey].config = {};
        for (const configKey in updatedAction.config) {
          const updatedConfig = updatedAction.config[configKey];
          if (updatedConfig?.choices != null) {
            if (!this.agent.data.actions[actionKey].config[configKey]) {
              this.agent.data.actions[actionKey].config[configKey] = {};
            }
            this.agent.data.actions[actionKey].config[configKey].choices = Array.isArray(updatedConfig.choices)
              ? [...updatedConfig.choices] : updatedConfig.choices;
          }
        }
      }
      this.syncDynamicChildren(updatedAgent);
    },

    syncDynamicChildren(updatedAgent) {
      if (!updatedAgent?.actions || !this.agent?.actions) return;
      const serverActions = updatedAgent.actions;
      const serverDataActions = updatedAgent.data?.actions || {};
      for (const actionKey in serverActions) {
        const serverAction = serverActions[actionKey];
        const serverBlobField = serverAction?.config?.dynamic_children;
        if (!serverBlobField) continue;
        if (!this.agent.actions[actionKey]?.config?.dynamic_children) continue;
        this.agent.actions[actionKey].config.dynamic_children.value = serverBlobField.value;
        if (this.agent.data?.actions?.[actionKey]?.config?.dynamic_children) {
          this.agent.data.actions[actionKey].config.dynamic_children.value = serverBlobField.value;
        }
      }
      for (const actionKey in serverActions) {
        const serverAction = serverActions[actionKey];
        if (!serverAction || !serverAction.parent_key) continue;
        if (this.agent.actions[actionKey]) continue;
        this.agent.actions[actionKey] = JSON.parse(JSON.stringify(serverAction));
        if (serverDataActions[actionKey]) {
          this.agent.data.actions[actionKey] = JSON.parse(JSON.stringify(serverDataActions[actionKey]));
        }
      }
      for (const actionKey of Object.keys(this.agent.actions)) {
        const localAction = this.agent.actions[actionKey];
        if (!localAction || !localAction.parent_key) continue;
        if (!serverActions[actionKey]) {
          delete this.agent.actions[actionKey];
          if (this.agent.data?.actions?.[actionKey]) delete this.agent.data.actions[actionKey];
          if (this.tab === actionKey) this.tab = '_config';
        }
      }
    },
  }
}
</script>

<style>
.scrollable-content {
  overflow-y: auto;
  max-height: 80vh;
  padding-right: 16px;
}

/* Vuetify's v-window has overflow: hidden for slide transitions, which
   clips v-slider's `thumb-label="always"` bubble when a slider is the
   first child in a tab. Give the window-item internal top padding so the
   slider has clearance below the v-window's clip edge. */
.scrollable-content .v-window-item {
  padding-top: 24px;
}

.checkbox-right {
  display: flex;
  justify-content: flex-end;
}
</style>

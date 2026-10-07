<template>
    <v-alert
        v-if="!sceneOnDisk"
        type="info"
        variant="text"
        density="compact"
        class="mt-4"
    >
        Save the scene first before adding per-scene prompt finalization overrides.
    </v-alert>

    <v-alert
        v-else-if="optedOut"
        type="info"
        variant="text"
        density="compact"
        class="mt-4"
    >
        This scene has opted out of per-scene agent settings. Link a settings file under
        Scene &rarr; Settings to edit prompt finalization overrides here.
    </v-alert>

    <div v-else-if="actionSchema">
        <v-alert density="compact" variant="tonal" color="primary" class="mt-4 mb-3" icon="mdi-movie-open-cog-outline">
            <div class="text-body-small">
                These are the Visualizer agent's scene overrides for Prompt Finalization, stored in
                <code v-if="sceneProjectName">{{ sceneProjectName }}/{{ sceneSettingsDirname }}/{{ effectiveFilename }}</code>
                <code v-else>{{ sceneSettingsDirname }}/{{ effectiveFilename }}</code>
            </div>
        </v-alert>
        <div class="text-body-small text-muted mb-3">
            <v-icon size="x-small" class="mr-1">mdi-gesture-tap-button</v-icon>
            Click <v-icon size="x-small" class="mx-1">mdi-link-variant-off</v-icon> next to a field to activate an override for this scene.
        </div>

        <AgentSceneSettings
            :action="actionSchema"
            :action-schema="actionSchema"
            :agent-actions="visualAgent.actions"
            :app-config="appConfig"
            :templates="templates"
            :overlay="localOverrides"
            :overrides="localOverrides.actions[ACTION_KEY] || {}"
            @update:overrides="updateActionOverrides"
            @change="dirty = true"
        />

        <SceneOverridePendingSave v-if="pendingSave" class="mt-3" />
        <v-alert
            v-if="error"
            type="error"
            variant="tonal"
            density="compact"
            closable
            class="mt-3 text-body-small"
            @click:close="error = null"
        >{{ error }}</v-alert>

        <div class="mt-4">
            <v-btn
                color="primary"
                variant="tonal"
                prepend-icon="mdi-content-save"
                :disabled="!dirty || saving"
                :loading="saving"
                @click="saveSceneOverrides"
            >
                Save
            </v-btn>
            <v-btn
                class="ml-2"
                color="cancel"
                variant="text"
                prepend-icon="mdi-cancel"
                :disabled="!dirty || saving"
                @click="resetOverrides"
            >
                Reset
            </v-btn>
        </div>
    </div>

    <v-alert
        v-else
        type="info"
        variant="text"
        density="compact"
        class="mt-4"
    >
        Visualizer agent status not available yet.
    </v-alert>
</template>

<script>
import AgentSceneSettings from './AgentSceneSettings.vue';
import SceneOverridePendingSave from './SceneOverridePendingSave.vue';
import {
    DEFAULT_SCENE_AGENT_SETTINGS_FILENAME,
    SCENE_AGENT_SETTINGS_DIRNAME,
    actionOverridePatch,
    setActionOverrideSlice,
} from '@/constants/sceneAgentSettings';

const ACTION_KEY = '_prompt_finalization';

export default {
    name: 'WorldStateManagerSceneVisualsFinalizers',
    components: {
        AgentSceneSettings,
        SceneOverridePendingSave,
    },
    props: {
        scene: Object,
        agentStatus: Object,
        appConfig: Object,
        templates: Object,
    },
    inject: ['patchSceneAgentValues', 'sceneOverridesState'],
    data() {
        return {
            ACTION_KEY,
            localOverrides: { actions: {} },
            // the slice the edits started from: Save writes only what differs
            seedSlice: {},
            dirty: false,
            saving: false,
            error: null,
        }
    },
    computed: {
        visualAgent() {
            return this.agentStatus?.visual || null;
        },
        actionSchema() {
            return this.visualAgent?.actions?.[ACTION_KEY] || null;
        },
        sceneOnDisk() {
            return !!(this.scene?.data?.filename && this.scene?.data?.project_name);
        },
        optedOut() {
            return !!this.scene?.data?.agent_settings_opted_out;
        },
        sceneProjectName() {
            return this.scene?.data?.project_name || null;
        },
        sceneSettingsDirname() {
            return SCENE_AGENT_SETTINGS_DIRNAME;
        },
        effectiveFilename() {
            return this.scene?.data?.agent_settings_file || DEFAULT_SCENE_AGENT_SETTINGS_FILENAME;
        },
        pendingSave() {
            return !!this.sceneOverridesState?.()?.pendingSave;
        },
    },
    watch: {
        'visualAgent.scene_overrides': {
            handler() {
                // Reseed from agent status unless the user has unsaved edits.
                if (!this.dirty) this.resetOverrides();
            },
            immediate: true,
            deep: true,
        },
    },
    methods: {
        resetOverrides() {
            const seed = this.visualAgent?.scene_overrides || {};
            this.localOverrides = {
                actions: seed.actions ? JSON.parse(JSON.stringify(seed.actions)) : {},
            };
            this.seedSlice = JSON.parse(JSON.stringify(this.localOverrides.actions[ACTION_KEY] || {}));
            this.dirty = false;
            this.error = null;
        },

        updateActionOverrides(perActionOverride) {
            this.localOverrides = {
                actions: setActionOverrideSlice(this.localOverrides.actions, ACTION_KEY, perActionOverride),
            };
        },

        saveSceneOverrides() {
            const written = JSON.parse(JSON.stringify(this.localOverrides.actions[ACTION_KEY] || {}));
            const patch = actionOverridePatch('visual', ACTION_KEY, this.seedSlice, written);
            if (!patch.set.length && !patch.clear.length) {
                this.resetOverrides();
                return;
            }
            this.saving = true;
            this.error = null;
            this.patchSceneAgentValues(patch, 'Prompt finalization', {
                // the status frame that follows reseeds the editor
                onComplete: () => {
                    this.saving = false;
                    this.seedSlice = written;
                    // an edit made while the save was in flight is still unsaved
                    this.dirty = JSON.stringify(this.localOverrides.actions[ACTION_KEY] || {}) !== JSON.stringify(written);
                },
                onError: (message) => {
                    this.saving = false;
                    this.error = message;
                },
            });
        },
    },
}
</script>

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
            <div class="text-caption">
                These are the Visualizer agent's scene overrides for Prompt Finalization, stored in
                <code v-if="sceneProjectName">{{ sceneProjectName }}/{{ sceneSettingsDirname }}/{{ effectiveFilename }}</code>
                <code v-else>{{ sceneSettingsDirname }}/{{ effectiveFilename }}</code>
            </div>
        </v-alert>
        <div class="text-caption text-muted mb-3">
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

        <div class="mt-4">
            <v-btn
                color="primary"
                variant="tonal"
                prepend-icon="mdi-content-save"
                :disabled="!dirty"
                @click="saveSceneOverrides"
            >
                Save
            </v-btn>
            <v-btn
                class="ml-2"
                color="cancel"
                variant="text"
                prepend-icon="mdi-cancel"
                :disabled="!dirty"
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
import {
    DEFAULT_SCENE_AGENT_SETTINGS_FILENAME,
    SCENE_AGENT_SETTINGS_DIRNAME,
    setActionOverrideSlice,
} from '@/constants/sceneAgentSettings';

const ACTION_KEY = '_prompt_finalization';

export default {
    name: 'WorldStateManagerSceneVisualsFinalizers',
    components: {
        AgentSceneSettings,
    },
    props: {
        scene: Object,
        agentStatus: Object,
        appConfig: Object,
        templates: Object,
    },
    inject: ['getWebsocket'],
    data() {
        return {
            ACTION_KEY,
            // Full sparse overlay for the visual agent — save_scene_overrides
            // replaces the agent's whole entry, so untouched actions must be
            // carried along.
            localOverrides: { actions: {} },
            dirty: false,
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
            this.dirty = false;
        },

        updateActionOverrides(perActionOverride) {
            this.localOverrides = {
                actions: setActionOverrideSlice(this.localOverrides.actions, ACTION_KEY, perActionOverride),
            };
        },

        saveSceneOverrides() {
            const payload = {
                type: 'agent_config',
                action: 'save_scene_overrides',
                agent_type: 'visual',
                override: this.localOverrides,
            };
            // No file linked yet — fall back to the default filename so other
            // scenes in this project auto-link to it.
            if (!this.scene?.data?.agent_settings_file) {
                payload.filename = DEFAULT_SCENE_AGENT_SETTINGS_FILENAME;
            }
            this.getWebsocket().send(JSON.stringify(payload));
            this.dirty = false;
        },
    },
}
</script>

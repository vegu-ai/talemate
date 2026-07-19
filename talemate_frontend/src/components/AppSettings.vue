<template>
    <v-card variant="text" v-if="app_config !== null">
        <v-toolbar rounded="md" density="compact" color="grey-darken-4" class="pl-2 mb-1 app-settings-toolbar">
            <v-icon class="mr-2" color="primary">{{ currentPage?.icon || 'mdi-cog' }}</v-icon>
            <span class="text-subtitle-2">{{ currentPage?.group }} <span class="text-muted">/</span> {{ currentPage?.title }}</span>
            <v-spacer></v-spacer>
            <v-chip v-if="externalChange" size="small" label color="warning" variant="text" prepend-icon="mdi-alert-circle-outline" class="mr-2">
                Changed outside this view — saving overwrites
                <v-tooltip activator="parent" location="bottom" max-width="400">The configuration was changed elsewhere (another window or the help agent) while you have unsaved edits here. Discard to load the latest, or save to overwrite.</v-tooltip>
            </v-chip>
            <span v-if="dirty" class="text-muted text-caption mr-2">Unsaved changes.</span>
            <v-btn v-if="dirty" color="muted" variant="text" prepend-icon="mdi-undo" @click="discard">Discard</v-btn>
            <v-btn color="primary" variant="text" prepend-icon="mdi-check-circle-outline" :disabled="!dirty || embeddingsBusy" @click="saveConfig">Save</v-btn>
        </v-toolbar>

        <!-- surface-colored canvas: the reused editors were designed against the
             old modal's card surface — on the bare viewport background their
             internal surfaces read as disconnected grey islands -->
        <v-sheet class="app-settings-content pa-4" rounded="md">
            <v-window v-model="page" :touch="false">
                <v-window-item value="gameplay">
                    <AppSettingsGameplay :config="app_config" />
                </v-window-item>
                <v-window-item value="player-character">
                    <AppSettingsPlayerCharacter :config="app_config" />
                </v-window-item>
                <v-window-item value="appearance-messages">
                    <AppSettingsPageHeader title="Messages" icon="mdi-script-text">
                        Style the different message types in the scene view. Changes preview live in the scene while you edit.
                    </AppSettingsPageHeader>
                    <AppConfigAppearanceScene ref="appearance-messages" :immutableConfig="app_config" :sceneActive="sceneActive" @changed="onAppearanceChanged"></AppConfigAppearanceScene>
                </v-window-item>
                <v-window-item value="appearance-visuals">
                    <AppSettingsPageHeader title="Visuals" icon="mdi-image-outline">
                        Message visuals and scene backdrop behavior.
                    </AppSettingsPageHeader>
                    <AppConfigAppearanceAssets ref="appearance-visuals" :immutableConfig="app_config" :sceneActive="sceneActive" @changed="onAppearanceChanged"></AppConfigAppearanceAssets>
                </v-window-item>
                <v-window-item value="api-keys">
                    <AppSettingsApiKeys :config="app_config" />
                </v-window-item>
                <v-window-item value="env-variables">
                    <AppSettingsEnvVariables :config="app_config" />
                </v-window-item>
                <v-window-item value="presets-inference">
                    <AppConfigPresetsInference ref="presets-inference" :immutableConfig="app_config" @update="onPresetsChanged"></AppConfigPresetsInference>
                </v-window-item>
                <v-window-item value="presets-embeddings">
                    <AppConfigPresetsEmbeddings
                    ref="presets-embeddings"
                    @busy="() => busy = true"
                    @done="() => busy = false"
                    :clientStatus="clientStatus"
                    :memoryAgentStatus="agentStatus.memory || null"
                    :immutableConfig="app_config"
                    :sceneActive="sceneActive"
                    @update="onPresetsChanged"
                    ></AppConfigPresetsEmbeddings>
                </v-window-item>
                <v-window-item value="presets-system-prompts">
                    <AppConfigPresetsSystemPrompts
                        ref="presets-system-prompts"
                        :immutableConfig="app_config"
                        :system-prompt-defaults="app_config.system_prompt_defaults"
                        @update="onPresetsChanged"
                    ></AppConfigPresetsSystemPrompts>
                </v-window-item>
                <v-window-item value="content-classification">
                    <AppSettingsStringList
                        title="Content Classification"
                        icon="mdi-cube-scan"
                        input-label="Add content classification (Press enter to add)"
                        :list="app_config.creator.content_context"
                        @update:list="(list) => app_config.creator.content_context = list">
                        Available content classification choices when generating characters or scenarios.
                    </AppSettingsStringList>
                </v-window-item>
                <v-window-item value="perspective-presets">
                    <AppSettingsStringList
                        title="Perspective Presets"
                        icon="mdi-eye-outline"
                        input-label="Add perspective preset (Press enter to add)"
                        :list="app_config.creator.perspective_presets"
                        @update:list="(list) => app_config.creator.perspective_presets = list">
                        Reusable narrative perspective / tense strings offered in the scene outline. Use <code>{player_name}</code> as a placeholder for the player character — it will be substituted at prompt render time.
                    </AppSettingsStringList>
                </v-window-item>
            </v-window>
        </v-sheet>
    </v-card>
    <v-card v-else variant="text">
        <v-card-text>
            <v-progress-circular indeterminate="disable-shrink" color="primary" size="20"></v-progress-circular>
        </v-card-text>
    </v-card>
</template>

<script>
import AppSettingsPageHeader from './AppSettingsPageHeader.vue';
import AppSettingsGameplay from './AppSettingsGameplay.vue';
import AppSettingsPlayerCharacter from './AppSettingsPlayerCharacter.vue';
import AppSettingsApiKeys from './AppSettingsApiKeys.vue';
import AppSettingsEnvVariables from './AppSettingsEnvVariables.vue';
import AppSettingsStringList from './AppSettingsStringList.vue';
import AppConfigAppearanceScene from './AppConfigAppearanceScene.vue';
import AppConfigAppearanceAssets from './AppConfigAppearanceAssets.vue';
import AppConfigPresetsInference from './AppConfigPresetsInference.vue';
import AppConfigPresetsEmbeddings from './AppConfigPresetsEmbeddings.vue';
import AppConfigPresetsSystemPrompts from './AppConfigPresetsSystemPrompts.vue';
import { settingsPage, mapLegacyLocation } from '../utils/appSettingsRegistry.js';

export default {
    name: 'AppSettings',
    components: {
        AppSettingsPageHeader,
        AppSettingsGameplay,
        AppSettingsPlayerCharacter,
        AppSettingsApiKeys,
        AppSettingsEnvVariables,
        AppSettingsStringList,
        AppConfigAppearanceScene,
        AppConfigAppearanceAssets,
        AppConfigPresetsInference,
        AppConfigPresetsEmbeddings,
        AppConfigPresetsSystemPrompts,
    },
    props: {
        agentStatus: Object,
        sceneActive: Boolean,
        clientStatus: Object,
        visible: Boolean,
    },
    emits: [
        'appearance-preview',
        'appearance-preview-clear',
        'page-changed',
    ],
    data() {
        return {
            page: 'gameplay',
            app_config: null,
            snapshot: null,
            pendingConfig: null,
            externalChange: false,
            saving: false,
            busy: false,
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'requestAppConfig'],
    computed: {
        dirty() {
            if (this.app_config === null || this.snapshot === null) {
                return false;
            }
            return JSON.stringify(this.app_config) !== this.snapshot;
        },
        currentPage() {
            return settingsPage(this.page);
        },
        embeddingsBusy() {
            // the embeddings editor reports busy while the memory agent
            // applies an embedding set — only block saving from that page
            return this.busy && this.page === 'presets-embeddings';
        },
    },
    watch: {
        page(newPage) {
            this.$emit('page-changed', newPage);
        },
        visible(isVisible) {
            if (!isVisible) {
                // leaving the settings tab — the scene should show the saved
                // appearance again, not an unsaved preview
                this.$emit('appearance-preview-clear');
            } else {
                if (this.app_config === null) {
                    this.requestAppConfig();
                }
                if (this.dirty) {
                    // returning with unsaved appearance edits — restore the preview
                    this.emitAppearancePreview();
                }
            }
        },
    },
    methods: {
        uxSnapshot() {
            // what the settings view shows, for the help agent's UX snapshot.
            // `dirty` gates help-agent config writes backend-side: only
            // unsaved edits here are a conflict, an idle settings tab is not
            if (!this.visible) return null;
            return { tab: 'settings', page: this.page, dirty: this.dirty };
        },
        navigate(page, anchor = null, item = null) {
            if (page) {
                this.page = page;
            }
            this.$nextTick(() => {
                // wait for the (lazily mounted) window item before selecting
                // or scrolling
                setTimeout(() => {
                    if (item) {
                        const ref = this.$refs[this.page];
                        if (ref && ref.setSelection) {
                            ref.setSelection(item);
                        }
                    }
                    if (anchor) {
                        this.flashAnchor(anchor);
                    }
                }, 300);
            });
        },
        // legacy openAppConfig(tab, page, item) entry point — still used by
        // backend uxActions and older callers
        openLegacy(tab, page, item = null) {
            const location = mapLegacyLocation(tab, page, item);
            if (location.page) {
                this.navigate(location.page, location.anchor, location.item);
            }
        },
        flashAnchor(anchor) {
            const el = this.$el.querySelector(`[data-setting-anchor="${anchor}"]`);
            if (!el) {
                return;
            }
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.classList.remove('setting-flash');
            // restart the animation if it was already applied
            void el.offsetWidth;
            el.classList.add('setting-flash');
            setTimeout(() => el.classList.remove('setting-flash'), 2500);
        },

        adoptConfig(config) {
            // the app_config payload emitted alongside a save lacks
            // system_prompt_defaults (only request_app_config and
            // config-changed broadcasts include it) — carry it over
            if (config.system_prompt_defaults === undefined && this.app_config?.system_prompt_defaults !== undefined) {
                config = { ...config, system_prompt_defaults: this.app_config.system_prompt_defaults };
            }
            // deep-copy: ws payloads are parsed once and shared with every
            // registered handler (TalemateApp.appConfig stores the same
            // object) — editing an aliased working copy would leak unsaved
            // edits app-wide and make Discard leave stale state behind
            this.snapshot = JSON.stringify(config);
            this.app_config = JSON.parse(this.snapshot);
            this.pendingConfig = null;
            this.externalChange = false;
        },

        discard() {
            const restore = this.pendingConfig !== null ? this.pendingConfig : JSON.parse(this.snapshot);
            this.adoptConfig(restore);
            this.$emit('appearance-preview-clear');
        },

        mergeSubcomponentConfigs() {
            // ref-based editors (presets, appearance) keep their own working
            // state — fold it back into the config working copy.
            // NOTE: the inference and embeddings editors shallow-copy their
            // immutableConfig, so their nested preset objects ALIAS
            // app_config.presets.* — edits there mutate the working copy
            // directly (which is what drives dirty tracking for those pages),
            // and the assignments below are no-ops for them. If those editors
            // ever deep-copy, dirty tracking needs an explicit update event.
            const inference = this.$refs['presets-inference'];
            if (inference) {
                this.app_config.presets.inference = inference.config.inference;
                this.app_config.presets.inference_groups = inference.config.inference_groups;
            }
            const embeddings = this.$refs['presets-embeddings'];
            if (embeddings) {
                this.app_config.presets.embeddings = embeddings.config.embeddings;
            }
            const systemPrompts = this.$refs['presets-system-prompts'];
            if (systemPrompts) {
                this.app_config.system_prompts = systemPrompts.config;
            }
            const appearanceScene = this.$refs['appearance-messages'];
            if (appearanceScene) {
                this.app_config.appearance.scene = appearanceScene.config;
            }
            const appearanceAssets = this.$refs['appearance-visuals'];
            if (appearanceAssets) {
                if (!this.app_config.appearance.scene) {
                    this.app_config.appearance.scene = {};
                }
                if (appearanceAssets.get_config) {
                    this.app_config.appearance.scene.message_assets = appearanceAssets.get_config();
                }
                if (appearanceAssets.get_auto_attach_assets) {
                    this.app_config.appearance.scene.auto_attach_assets = appearanceAssets.get_auto_attach_assets();
                }
                if (appearanceAssets.get_backdrop_settings) {
                    Object.assign(this.app_config.appearance.scene, appearanceAssets.get_backdrop_settings());
                }
            }
        },

        onPresetsChanged() {
            this.mergeSubcomponentConfigs();
        },

        onAppearanceChanged() {
            this.mergeSubcomponentConfigs();
            this.emitAppearancePreview();
        },

        emitAppearancePreview() {
            this.$emit('appearance-preview', this.app_config.appearance);
        },

        handleMessage(message) {
            if (message.type == "app_config") {
                if (this.dirty) {
                    // don't clobber unsaved edits — stash the incoming config.
                    // Broadcasts fire on reconnects and unrelated saves too, so
                    // only flag an external change when the content actually
                    // differs from the baseline we're editing against.
                    this.pendingConfig = message.data;
                    if (!this.saving && JSON.stringify(message.data) !== this.snapshot) {
                        this.externalChange = true;
                    }
                } else {
                    this.adoptConfig(message.data);
                }
                return;
            }

            if (message.type == 'config') {
                if (message.action == 'operation_done' && message.error) {
                    // failed save (e.g. backend validation) — save_complete
                    // never arrives; a stuck saving flag would suppress
                    // external-change detection for the rest of the session
                    this.saving = false;
                    return;
                }
                if (message.action == 'save_complete') {
                    // adopt the server-normalized config broadcast alongside
                    // the save when available
                    if (this.pendingConfig !== null) {
                        this.adoptConfig(this.pendingConfig);
                    } else {
                        this.snapshot = JSON.stringify(this.app_config);
                        this.externalChange = false;
                    }
                    this.saving = false;
                    this.$emit('appearance-preview-clear');
                }
            }
        },

        sendRequest(data) {
            data.type = 'config';
            this.getWebsocket().send(JSON.stringify(data));
        },

        saveConfig() {
            this.mergeSubcomponentConfigs();
            this.saving = true;
            this.sendRequest({
                action: 'save',
                config: this.app_config,
            });
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
        this.requestAppConfig();
    },
}
</script>

<style scoped>
.app-settings-toolbar {
    position: sticky;
    top: 0;
    z-index: 2;
}

.app-settings-content {
    max-width: 1200px;
}
</style>

<style>
.setting-flash {
    animation: setting-flash-pulse 2.5s ease-out;
    border-radius: 4px;
}

@keyframes setting-flash-pulse {
    0% {
        background-color: rgba(var(--v-theme-primary), 0.25);
    }
    100% {
        background-color: transparent;
    }
}
</style>

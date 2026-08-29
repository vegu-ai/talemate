<template>
    <v-card variant="text" v-if="app_config !== null">
        <v-toolbar rounded="md" density="compact" color="mutedbg" class="pl-2 mb-1 app-settings-toolbar">
            <v-icon class="mr-2" color="primary">{{ currentPage?.icon || 'mdi-cog' }}</v-icon>
            <span class="text-title-small mr-4">{{ currentPage?.group }} <span class="text-muted">/</span> {{ currentPage?.title }}</span>
            <v-btn color="primary" variant="text" prepend-icon="mdi-check-circle-outline" :disabled="!canSave" @click="saveConfig">Save</v-btn>
            <v-btn v-if="dirty" color="muted" variant="text" prepend-icon="mdi-undo" @click="discard">Discard</v-btn>
            <span v-if="dirty" class="text-muted text-body-small mr-2">Unsaved changes.</span>
            <v-chip v-if="saveError" size="small" label color="error" variant="text" prepend-icon="mdi-alert-circle-outline" class="mr-2">
                {{ saveErrorText }}
                <v-tooltip v-if="saveErrorIsApplyFailure" activator="parent" location="bottom" max-width="400">The settings were stored, but the running clients and agents are still the old ones. Saving again re-applies the stored configuration — no further edits are needed.</v-tooltip>
            </v-chip>
            <v-chip v-if="externalChange" size="small" label color="warning" variant="text" prepend-icon="mdi-alert-circle-outline" class="mr-2">
                Changed outside this view — saving overwrites
                <v-tooltip activator="parent" location="bottom" max-width="400">The configuration was changed elsewhere (another window or the help agent) while you have unsaved edits here. Discard to load the latest, or save to overwrite.</v-tooltip>
            </v-chip>
            <v-spacer></v-spacer>
        </v-toolbar>

        <!-- surface-colored canvas: the reused editors were designed against the
             old modal's card surface — on the bare viewport background their
             internal surfaces read as disconnected grey islands -->
        <v-sheet class="app-settings-content pa-4" rounded="md">
            <!-- the page header for every page — page components carry none of their own -->
            <AppSettingsPageHeader v-if="currentPage" :title="currentPage.title" :icon="currentPage.icon">
                <div v-if="currentPage.descriptionHtml" v-html="currentPage.descriptionHtml"></div>
                <template v-else>{{ currentPage.description }}</template>
            </AppSettingsPageHeader>
            <v-window v-model="page" :touch="false">
                <v-window-item value="gameplay">
                    <AppSettingsGameplay :config="app_config" />
                </v-window-item>
                <v-window-item value="player-character">
                    <AppSettingsPlayerCharacter :config="app_config" />
                </v-window-item>
                <v-window-item value="sound">
                    <AppSettingsSound :config="app_config" />
                </v-window-item>
                <v-window-item value="appearance-theme">
                    <AppConfigAppearanceTheme ref="appearance-theme" :immutableConfig="app_config" :worldStateTemplates="worldStateTemplates" :saveWouldOverwrite="configDirty"></AppConfigAppearanceTheme>
                </v-window-item>
                <v-window-item value="appearance-messages">
                    <AppConfigAppearanceScene ref="appearance-messages" :immutableConfig="app_config" :sceneActive="sceneActive" @changed="onAppearanceChanged" @restore-from-theme="onAppearanceRestoredFromTheme"></AppConfigAppearanceScene>
                </v-window-item>
                <v-window-item value="appearance-visuals">
                    <AppConfigAppearanceAssets ref="appearance-visuals" :immutableConfig="app_config" :sceneActive="sceneActive" @changed="onAppearanceChanged"></AppConfigAppearanceAssets>
                </v-window-item>
                <v-window-item value="clients">
                    <AppSettingsClients ref="clients" :config="app_config" />
                </v-window-item>
                <v-window-item value="agents">
                    <AppSettingsAgents ref="agents" :config="app_config" :dirty="dirty"
                        @extra-dirty="(value) => setExtraDirty('agents', value)"
                        @extra-error="(error) => setSaveError(error)" />
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
                        input-label="Add content classification (Press enter to add)"
                        :list="app_config.creator.content_context"
                        @update:list="(list) => app_config.creator.content_context = list">
                    </AppSettingsStringList>
                </v-window-item>
                <v-window-item value="perspective-presets">
                    <AppSettingsStringList
                        input-label="Add perspective preset (Press enter to add)"
                        :list="app_config.creator.perspective_presets"
                        @update:list="(list) => app_config.creator.perspective_presets = list">
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
import AppSettingsSound from './AppSettingsSound.vue';
import AppSettingsAgents from './AppSettingsAgents.vue';
import AppSettingsApiKeys from './AppSettingsApiKeys.vue';
import AppSettingsClients from './AppSettingsClients.vue';
import AppSettingsEnvVariables from './AppSettingsEnvVariables.vue';
import AppSettingsStringList from './AppSettingsStringList.vue';
import AppConfigAppearanceScene from './AppConfigAppearanceScene.vue';
import AppConfigAppearanceTheme from './AppConfigAppearanceTheme.vue';
import AppConfigAppearanceAssets from './AppConfigAppearanceAssets.vue';
import AppConfigPresetsInference from './AppConfigPresetsInference.vue';
import AppConfigPresetsEmbeddings from './AppConfigPresetsEmbeddings.vue';
import AppConfigPresetsSystemPrompts from './AppConfigPresetsSystemPrompts.vue';
import { settingsPage, mapLegacyLocation, SETTINGS_PAGES } from '../utils/appSettingsRegistry.js';

export default {
    name: 'AppSettings',
    components: {
        AppSettingsPageHeader,
        AppSettingsGameplay,
        AppSettingsPlayerCharacter,
        AppSettingsSound,
        AppSettingsAgents,
        AppSettingsApiKeys,
        AppSettingsClients,
        AppSettingsEnvVariables,
        AppSettingsStringList,
        AppConfigAppearanceScene,
        AppConfigAppearanceTheme,
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
        worldStateTemplates: Object,
    },
    emits: [
        'appearance-preview',
        'appearance-preview-clear',
        'page-changed',
        'dirty-changed',
        'save-state-changed',
    ],
    data() {
        return {
            // opens on the first page of the menu — the registry's order is
            // the single source of truth for both
            page: SETTINGS_PAGES[0].id,
            app_config: null,
            snapshot: null,
            pendingConfig: null,
            externalChange: false,
            saving: false,
            // request id of the config save this view has in flight — the
            // save action is shared with the drawer and the wizard, so only
            // an id match identifies our own completion
            pendingSaveId: null,
            busy: false,
            saveError: null,
            // the last save was stored but not applied — the backend re-applies
            // it on the next save touching the same sections, so Save stays
            // armed to re-send the (unchanged) config as the retry. Only a save
            // that came back applied (or Discard) takes it down.
            applyFailed: false,
            // `saveError` is the apply failure itself, and not some later error
            // that replaced it — the retry hint and its tooltip describe THAT
            // message, so they hang off this and not off the arming above
            saveErrorIsApplyFailure: false,
            // page id -> page reports unsaved state of its own (see the
            // extra-changes contract next to validatePages)
            extraDirty: {},
            // a config save is in flight and pages with extra changes are
            // waiting for it to land before committing theirs
            pendingExtraCommit: false,
        }
    },
    inject: ['registerMessageHandler', 'requestAppConfig', 'sendConfigSave'],
    computed: {
        configDirty() {
            if (this.app_config === null || this.snapshot === null) {
                return false;
            }
            return JSON.stringify(this.app_config) !== this.snapshot;
        },
        dirty() {
            return this.configDirty || Object.values(this.extraDirty).some(Boolean);
        },
        currentPage() {
            return settingsPage(this.page);
        },
        embeddingsBusy() {
            // the embeddings editor reports busy while the memory agent
            // applies an embedding set — only block saving from that page
            return this.busy && this.page === 'presets-embeddings';
        },
        canSave() {
            // an unapplied save leaves nothing dirty to press Save on, so it
            // arms the button by itself — that save IS the retry
            return (this.dirty || this.applyFailed) && !this.embeddingsBusy;
        },
        saveErrorText() {
            // an apply failure already reads as a whole sentence from the
            // backend ("saved, but applying it failed") — what it doesn't say
            // is that the toolbar can still do something about it
            return this.saveErrorIsApplyFailure ? `${this.saveError} — press Save to retry.` : this.saveError;
        },
        saveState() {
            // what a save from outside this component (the unsaved changes
            // prompt) needs to know before offering one
            return { canSave: this.canSave, externalChange: this.externalChange };
        },
    },
    watch: {
        page(newPage) {
            this.$emit('page-changed', newPage);
        },
        dirty(isDirty) {
            this.$emit('dirty-changed', isDirty);
        },
        saveState(state) {
            this.$emit('save-state-changed', state);
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
            // unsaved edits here are a conflict, an idle settings tab is not.
            // Pages may add what they have selected (agent, client, mode)
            // through an opt-in `uxSnapshot()` of their own.
            //
            // Unsaved edits survive leaving the settings tab (that is what
            // "keep editing" does), and Save then pushes the whole working
            // copy — so `dirty` is reported off-screen too, or the refusal it
            // gates would be disarmed by switching tabs. What the user is
            // LOOKING at is only reported while the view is on screen.
            if (!this.visible) {
                return this.dirty ? { tab: 'settings', visible: false, dirty: true } : null;
            }
            const snapshot = { tab: 'settings', visible: true, page: this.page, dirty: this.dirty };
            const ref = this.$refs[this.page];
            if (ref && typeof ref.uxSnapshot === 'function') {
                Object.assign(snapshot, ref.uxSnapshot() || {});
            }
            return snapshot;
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

        // `system_prompt_defaults` and the resolved `theme` are server-derived
        // extras rather than config. Both the baseline and an incoming payload
        // go through here so the raw-JSON compare below never sees the two keys
        // in different positions — a carried-forward key lands wherever it was
        // spread on, and that alone would read as an outside change. The
        // carry-forward itself is a safety net at the websocket boundary: every
        // emitter sends both today.
        normalizedPayload(config, carryFrom = null) {
            const normalized = { ...config };
            const extras = ['system_prompt_defaults', 'theme'];
            const values = extras.map((key) => (
                normalized[key] !== undefined ? normalized[key] : carryFrom?.[key]
            ));
            extras.forEach((key) => delete normalized[key]);
            extras.forEach((key, index) => {
                if (values[index] !== undefined) {
                    normalized[key] = values[index];
                }
            });
            return normalized;
        },

        adoptConfig(config) {
            config = this.normalizedPayload(config, this.app_config);
            // deep-copy: ws payloads are parsed once and shared with every
            // registered handler (TalemateApp.appConfig stores the same
            // object) — editing an aliased working copy would leak unsaved
            // edits app-wide and make Discard leave stale state behind
            this.snapshot = JSON.stringify(config);
            this.app_config = JSON.parse(this.snapshot);
            this.pendingConfig = null;
            this.externalChange = false;
            // an armed retry outlives the config it was raised on — a
            // reconnect broadcast or a foreign save applied none of what is
            // still sitting stored, so its message stays up with it
            if (!this.applyFailed) {
                this.setSaveError(null);
            }
        },

        // The resolved theme is server-derived and no part of the draft (the
        // backend drops it on save), so unsaved edits must not hold a theme
        // change back — editing a theme and restoring the appearance from it is
        // one workflow. `appearance.theme` (the id) rides along for the same
        // reason: no settings page edits it — applying a theme writes it
        // server-side — so it moves with the baseline too. Held back, the
        // picker's Active chip goes stale and a later save of the stale draft
        // silently reverts the applied theme. The baseline moves with both, so
        // a theme that changed on its own is neither an unsaved edit nor an
        // external change.
        adoptTheme(theme, themeId) {
            if (theme === undefined && themeId === undefined) {
                return;
            }
            const baseline = JSON.parse(this.snapshot);
            if (theme !== undefined) {
                baseline.theme = theme;
            }
            if (themeId !== undefined) {
                baseline.appearance.theme = themeId;
            }
            this.snapshot = JSON.stringify(baseline);
            // through the snapshot, for the aliasing reason adoptConfig copies for
            const adopted = JSON.parse(this.snapshot);
            if (theme !== undefined) {
                this.app_config.theme = adopted.theme;
            }
            if (themeId !== undefined) {
                this.app_config.appearance.theme = adopted.appearance.theme;
            }
        },

        // The apply-failure decoration belongs to one message only — every
        // other error replaces it plain.
        setSaveError(error, applyFailure = false) {
            this.saveError = error;
            this.saveErrorIsApplyFailure = applyFailure;
        },

        discard() {
            const restore = this.pendingConfig !== null ? this.pendingConfig : JSON.parse(this.snapshot);
            // the retry goes with the edits it was raised on — back on the
            // stored config there is nothing here to press Save on
            this.applyFailed = false;
            this.adoptConfig(restore);
            this.pendingExtraCommit = false;
            this.eachExtraChangePage((ref) => {
                if (typeof ref.discardExtraChanges === 'function') {
                    ref.discardExtraChanges();
                }
            });
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

        onAppearanceRestoredFromTheme(scene) {
            // the visuals editor owns the backdrop values in the merge below and
            // still holds the ones the restore replaced — refresh it off the
            // restored scene first, or the merge writes the old ones back
            this.app_config.appearance.scene = scene;
            const appearanceAssets = this.$refs['appearance-visuals'];
            if (appearanceAssets && appearanceAssets.syncBackdropSettings) {
                appearanceAssets.syncBackdropSettings();
            }
            this.mergeSubcomponentConfigs();
            this.emitAppearancePreview();
        },

        emitAppearancePreview() {
            this.$emit('appearance-preview', this.app_config.appearance);
        },

        handleMessage(message) {
            if (message.type == "app_config") {
                // only unsaved CONFIG edits can be clobbered by an incoming
                // config — a page's extra changes live elsewhere
                if (this.configDirty) {
                    // don't clobber unsaved edits — stash the incoming config.
                    // Broadcasts fire on reconnects and unrelated saves too, so
                    // only flag an external change when the content actually
                    // differs from the baseline we're editing against.
                    this.pendingConfig = message.data;
                    this.adoptTheme(message.data.theme, message.data.appearance?.theme);
                    const incoming = JSON.stringify(this.normalizedPayload(message.data, this.app_config));
                    if (!this.saving && incoming !== this.snapshot) {
                        this.externalChange = true;
                    }
                } else {
                    this.adoptConfig(message.data);
                }
                return;
            }

            if (message.type == 'config') {
                if (!this.pendingSaveId || message.request_id !== this.pendingSaveId) {
                    // config saves no longer come from this view alone — the
                    // clients/agents drawer and the onboarding wizard write
                    // through the same action, and other windows do too. Only
                    // the completion carrying OUR request id may adopt a
                    // config over unsaved edits here; the app_config handler
                    // above already stashed anything else and flagged it.
                    return;
                }
                if (message.action == 'operation_done' && message.error) {
                    // failed save (e.g. backend validation) — save_complete
                    // never arrives; a stuck saving flag would suppress
                    // external-change detection for the rest of the session
                    this.saving = false;
                    this.pendingSaveId = null;
                    const error = message.error.message || 'The configuration could not be saved.';
                    const applyFailed = message.stage == 'apply';
                    if (applyFailed) {
                        // the config half landed — only applying it to the
                        // running clients/agents failed, so the edits are
                        // saved and page-owned changes belong with them. The
                        // adopted config is what has to be sent again to
                        // re-run the apply.
                        this.applyFailed = true;
                        this.adoptSavedConfig();
                    } else {
                        // the config never landed, so page-owned changes that
                        // depend on it must not be committed either
                        this.pendingExtraCommit = false;
                    }
                    this.setSaveError(error, applyFailed);
                    return;
                }
                if (message.action == 'save_complete') {
                    // whatever an earlier apply failure left unapplied went out
                    // with this save and is applied now
                    this.applyFailed = false;
                    this.adoptSavedConfig();
                }
            }
        },

        // The saved config is now what the backend holds — adopt what it
        // broadcast alongside the save (when there was one) and let pages
        // commit the changes that were waiting for it.
        adoptSavedConfig() {
            this.pendingSaveId = null;
            if (this.pendingConfig !== null) {
                this.adoptConfig(this.pendingConfig);
            } else {
                this.snapshot = JSON.stringify(this.app_config);
                this.externalChange = false;
            }
            this.saving = false;
            if (this.pendingExtraCommit) {
                this.pendingExtraCommit = false;
                this.commitExtraChanges();
            }
            this.$emit('appearance-preview-clear');
        },

        // Pages may expose `validate()` -> {valid, error} to reject a save
        // that the backend would only fail on as a whole-config validation
        // error (which would block every other setting too).
        validatePages() {
            for (const page of SETTINGS_PAGES) {
                const ref = this.$refs[page.id];
                if (!ref || typeof ref.validate !== 'function') {
                    continue;
                }
                const result = ref.validate();
                if (result && result.valid === false) {
                    return { page: page.id, error: result.error || `${page.title}: invalid settings` };
                }
            }
            return null;
        },

        // Extra-changes contract (opt-in, same shape as `validate()`) — for a
        // page holding state that does not live in the app config, so this
        // toolbar's Save has to reach it:
        //
        //   hasExtraChanges()      -> bool (also emit `extra-dirty`)
        //   prepareExtraChanges()  -> Promise<bool>; false aborts the save
        //   commitExtraChanges()   -> send; runs once the config save landed
        //   discardExtraChanges()  -> drop; runs on Discard
        //   `extra-error` event    -> failures, surfaced by the toolbar
        eachExtraChangePage(fn) {
            for (const page of SETTINGS_PAGES) {
                const ref = this.$refs[page.id];
                if (ref && typeof ref.hasExtraChanges === 'function' && ref.hasExtraChanges()) {
                    fn(ref, page);
                }
            }
        },

        setExtraDirty(pageId, value) {
            this.extraDirty[pageId] = value;
        },

        commitExtraChanges() {
            this.eachExtraChangePage((ref) => {
                if (typeof ref.commitExtraChanges === 'function') {
                    ref.commitExtraChanges();
                }
            });
        },

        async saveConfig() {
            if (!this.canSave) {
                // callers outside this component (the unsaved changes prompt)
                // can't see what disables the toolbar's Save button
                return;
            }
            this.mergeSubcomponentConfigs();
            const invalid = this.validatePages();
            if (invalid) {
                // take the user to the offending page and leave the config
                // untouched — nothing is sent
                this.setSaveError(invalid.error);
                this.navigate(invalid.page);
                return;
            }
            // pages with extra changes may need something from the user first
            // (the Agents page prompts for an agent-settings filename) — any
            // of them can abort the save before anything is sent
            const preparing = [];
            this.eachExtraChangePage((ref) => {
                if (typeof ref.prepareExtraChanges === 'function') {
                    preparing.push(ref.prepareExtraChanges());
                }
            });
            const prepared = await Promise.all(preparing);
            if (prepared.some((ok) => ok === false)) {
                return;
            }
            this.setSaveError(null);
            if (!this.configDirty && !this.applyFailed) {
                // nothing to save in the config itself — the extra changes are
                // the whole save. A failed apply is the exception: the config
                // it stored is the one adopted here, so sending it back
                // unchanged is exactly what re-runs the apply.
                this.commitExtraChanges();
                return;
            }
            // the host sends every config save so the request ids are handed
            // out in one place — and so a drawer save made while this one is
            // in flight stacks on this payload instead of the stale stored one
            // declared ahead of the send: the failure callback below is handed
            // to it and compares against the id it returns
            let requestId = null;
            requestId = this.sendConfigSave(this.app_config, {
                label: 'settings',
                // an answered save is handled by handleMessage, which clears
                // pendingSaveId — this is for the ones that are never answered
                // (a dropped socket), where a stuck `saving` would suppress
                // external-change detection for the rest of the session
                onError: (error) => {
                    if (this.pendingSaveId !== requestId) {
                        return;
                    }
                    this.saving = false;
                    this.pendingSaveId = null;
                    // the payload may or may not have been stored — page-owned
                    // changes must not be committed against a config that may
                    // never have landed, so they stay in their pages for the
                    // next save. `applyFailed` stays as it was: nothing here
                    // says the stored config was applied.
                    this.pendingExtraCommit = false;
                    this.setSaveError(error);
                },
            });
            if (!requestId) {
                this.setSaveError('The configuration could not be saved.');
                return;
            }
            this.pendingSaveId = requestId;
            this.saving = true;
            // only extras that were prepared as part of THIS save may ride
            // along on its completion — anything dirtied while the config was
            // in flight waits for its own explicit Save
            this.pendingExtraCommit = preparing.length > 0;
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
        this.requestAppConfig();
    },
}
</script>

<style scoped>
.app-settings-toolbar,
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

<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
    <v-row>
        <v-col cols="12">
            <v-form class="mt-4">
                <v-row>
                    <v-col cols="12" md="8" lg="6" xl="6">
                        <v-text-field
                            v-model="scene.data.title"
                            label="Title"
                            hint="The title of the scene. This will be displayed to the user when they play the scene."
                            :color="dirty['title'] ? 'dirty' : ''"
                            :disabled="busy['title']"
                            :loading="busy['title']"
                            @update:model-value="setFieldDirty('title')"
                            @blur="update(true)"
                            :placeholder="scene.data.title"
                        ></v-text-field>
                    </v-col>
                    <v-col cols="12" md="8" lg="6" xl="6">
                        <v-combobox
                            v-model="scene.data.context"
                            @update:model-value="setFieldDirty('context')"
                            @blur="update(true)"
                            :color="dirty['context'] ? 'dirty' : ''"
                            :items="appConfig ? appConfig.creator.content_context: []"
                            messages="This can seed the type of content that is generated, during narration, dialogue and world building."
                            label="Content Classification"
                        ></v-combobox>
                    </v-col>
                </v-row>
                <v-row>
                    <v-col cols="12" md="8" lg="6" xl="6">
                        <v-combobox
                            :model-value="perspectives.default"
                            :items="perspectivePresets"
                            label="Perspective and tense"
                            messages="The default narrative perspective, tense, and point of view. Used in all narration and dialogue prompts unless a per-speaker override is set."
                            :color="dirty['perspectives'] ? 'dirty' : ''"
                            :disabled="busy['perspectives']"
                            :loading="busy['perspectives']"
                            @update:model-value="onPerspectiveSelect('default', $event)"
                            @blur="update(true)"
                            placeholder="e.g., Third person limited, past tense"
                        ></v-combobox>
                    </v-col>
                    <v-col cols="12" md="8" lg="6" xl="6">
                        <v-expansion-panels variant="accordion" class="mb-2">
                            <v-expansion-panel>
                                <v-expansion-panel-title>
                                    <span>Per-speaker perspective overrides</span>
                                    <v-chip
                                        v-if="overrideCount > 0"
                                        size="x-small"
                                        color="primary"
                                        class="ml-3"
                                    >{{ overrideCount }} set</v-chip>
                                </v-expansion-panel-title>
                                <v-expansion-panel-text>
                                    <div class="text-caption text-medium-emphasis mb-3">
                                        Each override replaces the default perspective for that speaker. Empty fields fall back to the default.
                                    </div>
                                    <v-combobox
                                        :model-value="perspectives.player"
                                        :items="perspectivePresets"
                                        label="Perspective (you / player character)"
                                        messages="Used when the player character is speaking or acting."
                                        :color="dirty['perspectives'] ? 'dirty' : ''"
                                        :disabled="busy['perspectives']"
                                        @update:model-value="onPerspectiveSelect('player', $event)"
                                        @blur="update(true)"
                                        density="comfortable"
                                        class="mb-2"
                                    ></v-combobox>
                                    <v-combobox
                                        :model-value="perspectives.other"
                                        :items="perspectivePresets"
                                        label="Perspective (others / NPCs)"
                                        messages="Used when a non-player character is speaking or acting."
                                        :color="dirty['perspectives'] ? 'dirty' : ''"
                                        :disabled="busy['perspectives']"
                                        @update:model-value="onPerspectiveSelect('other', $event)"
                                        @blur="update(true)"
                                        density="comfortable"
                                        class="mb-2"
                                    ></v-combobox>
                                    <v-combobox
                                        :model-value="perspectives.narrator"
                                        :items="perspectivePresets"
                                        label="Perspective (narrator)"
                                        messages="Used for narration prompts (scene description, progression, character entry, etc.)."
                                        :color="dirty['perspectives'] ? 'dirty' : ''"
                                        :disabled="busy['perspectives']"
                                        @update:model-value="onPerspectiveSelect('narrator', $event)"
                                        @blur="update(true)"
                                        density="comfortable"
                                    ></v-combobox>
                                </v-expansion-panel-text>
                            </v-expansion-panel>
                        </v-expansion-panels>
                    </v-col>
                </v-row>
                <v-row>
                    <!-- scene description -->
                    <v-col cols="12">
                        <v-textarea
                            class="mt-1"
                            ref="description"
                            v-model="scene.data.description"
                            @update:model-value="setFieldDirty('description')"
                            @blur="update(true)"
                            :color="dirty['description'] ? 'dirty' : ''"
                            :disabled="busy['description']"
                            :loading="busy['description']"
                            label="Description"
                            rows="4"
                            auto-grow
                            max-rows="32"
                            hint="This will not be directly displayed to the user, but can be used to provide additional context to the scene, its goals and general information. This should not be used for lore dumps."
                        ></v-textarea>
                    </v-col>
                </v-row>
                <v-row>
                    <v-col cols="12">
                        <div class="d-flex align-center mb-2 intro-controls">
                            <v-spacer></v-spacer>
                            <ContextualGenerate
                                ref="contextualGenerate"
                                uid="wsm.scene_intro"
                                context="scene intro:scene intro"
                                :original="scene.data.intro"
                                :templates="templates"
                                :generation-options="generationOptions"
                                :history-aware="false"
                                :specify-length="true"
                                @generate="content => setIntroAndQueueUpdate(content)"
                            />
                        </div>
                        <div class="position-relative">
                            <v-textarea
                                class="mt-1"
                                ref="intro"
                                v-model="scene.data.intro"
                                label="Introduction text"
                                rows="10"
                                auto-grow
                                max-rows="32"

                                @update:model-value="setFieldDirty('intro')"
                                @blur="onIntroBlurSave"
                                :color="dirty['intro'] ? 'dirty' : ''"

                                :disabled="busy['intro']"
                                :loading="busy['intro']"
                                :hint="'The introduction to the scene. The first text the user sees as they load the scene. ' +autocompleteInfoMessage(busy['intro'])"
                                @keyup.ctrl.enter.stop="sendAutocompleteRequestForIntro"
                            ></v-textarea>
                            <AutocompleteRedoChip
                                :applied="introAutocompleteField?.state.applied || false"
                                :disabled="busy['intro']"
                                @redo="introAutocompleteField.redo()"
                                @undo="introAutocompleteField.undo()" />
                        </div>
                    </v-col>
                </v-row>
            </v-form>
        </v-col>
    </v-row>
    </div>


</template>

<script>

import ContextualGenerate from './ContextualGenerate.vue';
import { MAX_CONTENT_WIDTH } from '@/constants/layout';
import { createAutocompleteField } from '@/utils/autocompleteField';
import AutocompleteRedoChip from './AutocompleteRedoChip.vue';

const defaultPerspectives = () => ({ default: "", player: "", other: "", narrator: "" });

export default {
    name: "WorldStateManagerSceneOutline",
    components: {
        ContextualGenerate,
        AutocompleteRedoChip,
    },
    props: {
        immutableScene: Object,
        appConfig: Object,
        templates: Object,
        generationOptions: Object,
    },
    watch: {
        generationOptions: {
            immediate: true,
            handler(value) {
                console.log("generationOptions", value)
            }
        },
        immutableScene: {
            immediate: true,
            handler(value) {
                console.log("immutableScene", value)
                if(value && this.scene && value.name !== this.scene.name) {
                    this.scene = null;
                    this.selected = null;
                }
                if (!value) {
                    this.selected = null;
                    this.scene = null;
                } else {
                    this.scene = { ...value };
                    this.scene.data = { ...value.data };
                    this.scene.data.perspectives = {
                        ...defaultPerspectives(),
                        ...(value.data.perspectives || {}),
                    };
                }
            }
        },
        'scene.data.intro'() {
            this.introAutocompleteField?.onValueChange();
        },
    },
    data() {
        return {
            MAX_CONTENT_WIDTH,
            scene: null,
            contentContext: [],
            dirty: {},
            busy: {},
            updateTimeout: null,
            introAutocompleteField: null,
        }
    },
    created() {
        this.introAutocompleteField = createAutocompleteField({
            autocompleteRequest: this.autocompleteRequest,
            getValue: () => this.scene?.data?.intro || '',
            setValue: (v) => { if (this.scene?.data) this.scene.data.intro = v; },
            buildParams: () => ({
                partial: this.scene.data.intro,
                context: "scene intro:scene intro",
            }),
            onStart: () => { this.busy['intro'] = true; },
            onEnd: () => { this.busy['intro'] = false; },
        });
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'formatWorldStateTemplateString',
    ],
    emits:[
        'require-scene-save'
    ],
    computed: {
        perspectives() {
            return this.scene && this.scene.data && this.scene.data.perspectives
                ? this.scene.data.perspectives
                : defaultPerspectives();
        },
        perspectivePresets() {
            return this.appConfig && this.appConfig.creator && this.appConfig.creator.perspective_presets
                ? this.appConfig.creator.perspective_presets
                : [];
        },
        overrideCount() {
            const p = this.perspectives;
            return ["player", "other", "narrator"].filter(role => (p[role] || "").trim().length > 0).length;
        },
    },
    methods: {
        reset() {
            this.selected = null;
            this.character = null;
            this.templateApplicatorCallback = null;
            this.groupsOpen = [];
        },

        setIntroAndQueueUpdate(value) {
            this.scene.data.intro = value;
            this.queueUpdate('intro');
        },

        queueUpdate(name, delay = 1500) {
            if (this.updateTimeout !== null) {
                clearTimeout(this.updateTimeout);
            }

            this.dirty[name] = true;

            this.updateTimeout = setTimeout(() => {
                this.update();
            }, delay);
        },

        setFieldDirty(name) {
            this.dirty[name] = true;
        },

        onPerspectiveSelect(role, value) {
            this.scene.data.perspectives[role] = value || "";
            this.setFieldDirty('perspectives');
        },

        update(only_if_dirty = false) {

            if(only_if_dirty && !Object.values(this.dirty).some(v => v)) {
                return;
            }

            return this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_scene_outline',
                title: this.scene.data.title,
                context: this.scene.data.context,
                perspectives: { ...this.perspectives },
                intro: this.scene.data.intro,
                description: this.scene.data.description,
            }));
        },

        onIntroBlurSave() {
            // Guard: blur during autocomplete would save the un-stripped {hint}.
            if (this.busy['intro']) return;
            this.update(true);
        },

        sendAutocompleteRequestForIntro() {
            this.introAutocompleteField.request(this.$refs.intro);

        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'scene_outline_updated') {
                this.dirty = {};
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>

<style scoped>
.intro-controls {
    gap: 8px;
}
</style>

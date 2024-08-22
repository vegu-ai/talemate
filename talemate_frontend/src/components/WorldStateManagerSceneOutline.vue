<template>
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
                    @update:model-value="queueUpdate('title')"
                    :placeholder="scene.data.title"
                ></v-text-field>
            </v-col>
            <v-col cols="12" md="8" lg="6" xl="6">
                <v-combobox
                    v-model="scene.data.context"
                    @update:model-value="queueUpdate('context')"
                    :items="appConfig ? appConfig.creator.content_context: []"
                    messages="This can strongly influence the type of content that is generated, during narration, dialogue and world building."
                    label="Content context"
                ></v-combobox>
            </v-col>
        </v-row>
        <v-row>
            <!-- scene description -->
            <v-col cols="12">
                <v-textarea
                    class="mt-1"
                    ref="description"
                    v-model="scene.data.description"
                    @update:model-value="queueUpdate('description')"
                    :color="dirty['description'] ? 'primary' : ''"
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
                <ContextualGenerate 
                    ref="contextualGenerate"
                    uid="wsm.scene_intro"
                    context="scene intro:scene intro" 
                    :original="scene.data.intro"
                    :templates="templates"
                    :generation-options="generationOptions"
                    :history-aware="false"
                    @generate="content => setIntroAndQueueUpdate(content)"
                />
                <v-textarea
                    class="mt-1"
                    ref="intro"
                    v-model="scene.data.intro"
                    label="Introduction text"
                    rows="10"
                    auto-grow
                    max-rows="32"

                    @update:model-value="queueUpdate('intro')"
                    :color="dirty['intro'] ? 'dirty' : ''"
                    
                    :disabled="busy['intro']"
                    :loading="busy['intro']"
                    :hint="'The introduction to the scene. The first text the user sees as they load the scene. ' +autocompleteInfoMessage(busy['intro'])"
                    @keyup.ctrl.enter.stop="sendAutocompleteRequestForIntro"
                ></v-textarea>
            </v-col>
        </v-row>
    </v-form>
</template>

<script>

import ContextualGenerate from './ContextualGenerate.vue';

export default {
    name: "WorldStateManagerSceneOutline",
    components: {
        ContextualGenerate,
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
                }
            }
        },
    },
    data() {
        return {
            scene: null,
            contentContext: [],
            dirty: {},
            busy: {},
            updateTimeout: null,
        }
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

        update() {
            return this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_scene_outline',
                title: this.scene.data.title,
                context: this.scene.data.context,
                intro: this.scene.data.intro,
                description: this.scene.data.description,
            }));
        },

        sendAutocompleteRequestForIntro() {
            this.busy['intro'] = true;
            this.autocompleteRequest({
                partial: this.scene.data.intro,
                context: "scene intro:scene intro",
            }, (completion) => {
                this.scene.data.intro += completion;
                this.busy['intro'] = false;
            }, this.$refs.intro);

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
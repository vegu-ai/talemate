<template>

    <v-form class="mt-4">
        <v-row>
            <v-col cols="12" lg="6">
                <v-checkbox 
                    v-model="scene.data.immutable_save" 
                    @update:model-value="update()"
                    label="Locked save file" 
                    messages="When activated, progress such as conversation and narration cannot be saved to the current file and requires a `Save As` action.">
                </v-checkbox>
                <v-checkbox 
                    v-model="scene.data.experimental" 
                    @update:model-value="update()"
                    label="Experimental" 
                    messages="When activated, the scene will be tagged as experimental. This can be used to indicate whether a scene has components that could potentially make it unstable if used with weaker LLMs.">
                </v-checkbox>
            </v-col>
        </v-row>
        <v-row>
            <v-col cols="12" lg="6">
                <v-select
                    v-model="scene.data.writing_style_template"
                    :items="writingStyleTemplates"
                    label="Writing Style"
                    messages="Allows you to select one of your writing style templates to be used for content generation in this scene."
                    @update:model-value="update()"
                ></v-select>
            </v-col>
        </v-row>
    </v-form>
</template>

<script>

export default {
    name: "WorldStateManagerSceneSettings",
    props: {
        templates: Object,
        immutableScene: Object,
        appConfig: Object,
        generationOptions: Object,
    },
    watch: {
        immutableScene: {
            immediate: true,
            handler(value) {
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
    computed: {
        writingStyleTemplates() {
            let templates = Object.values(this.templates.by_type.writing_style).map((template) => {
                return {
                    value: `${template.group}__${template.uid}`,
                    title: template.name,
                    props: { subtitle: template.description }
                }
            });

            // add empty option to the top
            templates.unshift({
                value: null,
                title: 'None',
                props: { subtitle: 'No writing style template selected.' }
            });

            return templates;
        }
    },
    data() {
        return {
            scene: null,
            contentContext: [],
        }
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    methods: {
        update() {
            return this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_scene_settings',
                experimental: this.scene.data.experimental,
                immutable_save: this.scene.data.immutable_save,
                writing_style_template: this.scene.data.writing_style_template,
            }));
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
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
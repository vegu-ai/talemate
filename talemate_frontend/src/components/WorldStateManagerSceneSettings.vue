<template>
    <v-row>
        <v-col cols="12" ms="12" xl="8" xxl="5">
            <v-form class="mt-4">


                <v-row>
                    <v-col cols="12" lg="12">
                        <v-select
                            v-model="scene.data.writing_style_template"
                            :items="writingStyleTemplates"
                            label="Writing Style"
                            messages="Allows you to select one of your writing style templates to be used for content generation in this scene."
                            @update:model-value="update()"
                        ></v-select>
                    </v-col>
                </v-row>

                <v-row>
                    <v-col cols="12" lg="12">
                        <v-select
                            v-model="scene.data.agent_persona_templates.director"
                            :items="agentPersonaTemplates"
                            label="Director Persona"
                            messages="Choose a persona for the Director in this scene."
                            @update:model-value="update()"
                        ></v-select>
                    </v-col>
                </v-row>
        
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
        
                <v-divider class="mt-10 mb-10"></v-divider>
        
                <v-row>
                    <v-col cols="12" lg="6">
                        <v-select
                            v-model="scene.data.restore_from"
                            :items="scene.data.save_files"
                            label="Restore from"
                            messages="Specify a save file to restore from when using the Restore Scene button."
                            @update:model-value="update()"
                        ></v-select>
                    </v-col>
                    <v-col>
                        <v-btn :disabled="!scene.data.restore_from" color="delete" variant="text" prepend-icon="mdi-backup-restore" @click="restoreScene(false)">Restore Scene</v-btn>
                        <v-alert density="compact" variant="text" color="muted">This will restore the scene from the selected save file.
                        </v-alert>
                        <v-alert density="compact" variant="text" color="warning" v-if="scene?.data?.shared_context" class="mt-2">
                            <v-icon class="mr-1">mdi-alert</v-icon>
                            Note: The restored scene will be disconnected from its shared context since shared world context cannot be reconstructed to a specific revision.
                        </v-alert>
                    </v-col>
                </v-row>
        
        
            </v-form>
        </v-col>
    </v-row>

    <ConfirmActionPrompt 
        ref="confirmRestoreScene" 
        @confirm="restoreScene(true)" 
        actionLabel="Restore Scene" 
        icon="mdi-backup-restore"
        description="Are you sure you want to restore the scene from the selected save file?" />
</template>

<script>

import ConfirmActionPrompt from './ConfirmActionPrompt.vue';

export default {
    name: "WorldStateManagerSceneSettings",
    props: {
        templates: Object,
        immutableScene: Object,
        appConfig: Object,
        generationOptions: Object,
    },
    components: {
        ConfirmActionPrompt,
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
        },
        agentPersonaTemplates() {
            if(!this.templates || !this.templates.by_type.agent_persona) return [{ value: null, title: 'None' }];
            let templates = Object.values(this.templates.by_type.agent_persona).map((template) => {
                return {
                    value: `${template.group}__${template.uid}`,
                    title: template.name,
                    props: { subtitle: template.description }
                }
            });
            templates.unshift({ value: null, title: 'None', props: { subtitle: 'No persona selected.' } });
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
        restoreScene(confirmed=false) {

            if(!confirmed) {
                this.$refs.confirmRestoreScene.initiateAction();
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'restore_scene',
                scene: this.scene.name,
                restore_from: this.scene.data.restore_from,
            }));
        },
        update() {
            return this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_scene_settings',
                experimental: this.scene.data.experimental,
                immutable_save: this.scene.data.immutable_save,
                writing_style_template: this.scene.data.writing_style_template,
                agent_persona_templates: this.scene.data.agent_persona_templates || {},
                restore_from: this.scene.data.restore_from,
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
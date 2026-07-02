<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
    <v-row>
        <v-col cols="12">
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
                    <v-col cols="12" lg="12">
                        <v-select
                            v-model="scene.data.visual_style_template"
                            :items="visualStyleTemplates"
                            label="Visual Art Style"
                            messages="The default art style to use for visual prompt generation. Can be overridden in scene settings."
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

                <v-row>
                    <v-col cols="12" lg="6">
                        <v-select
                            v-model="agentSettingsSelection"
                            :items="agentSettingsOptions"
                            label="Agent settings file"
                            messages="Per-scene agent configuration overrides. Stored in the project's agent-settings/ folder. When auto-link is on, a default agent-settings.json (if present) is picked up automatically."
                            @update:model-value="updateAgentSettings"
                        ></v-select>
                    </v-col>
                    <v-col>
                        <v-alert v-if="scene?.data?.agent_settings_opted_out" density="compact" variant="text" color="muted">
                            <v-icon class="mr-1">mdi-link-variant-off</v-icon>
                            This scene is opted out of agent-settings overlays.
                        </v-alert>
                        <v-alert v-else-if="scene?.data?.agent_settings_file" density="compact" variant="text" color="muted">
                            <v-icon class="mr-1">mdi-link-variant</v-icon>
                            Linked to <strong>{{ scene.data.agent_settings_file }}</strong>. Edit overrides in the agent modal under the Scene tab.
                        </v-alert>
                        <v-alert v-else density="compact" variant="text" color="muted">
                            <v-icon class="mr-1">mdi-link-variant</v-icon>
                            Auto-link active. The first override set in the agent modal will create the linked file.
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
    </div>
</template>

<script>

import ConfirmActionPrompt from './ConfirmActionPrompt.vue';
import { MAX_CONTENT_WIDTH } from '@/constants/layout';

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
                    // Initialize visual_style_template to null if undefined to show "Use Agent Default"
                    if (this.scene.data && this.scene.data.visual_style_template === undefined) {
                        this.scene.data.visual_style_template = null;
                    }
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
        },
        // Current dropdown value for the agent-settings file picker.
        // Sentinel strings keep the v-select simple: "__opt_out__" for
        // explicit opt-out, "__auto__" for "no explicit link / auto-pick
        // the default if present", otherwise a literal filename.
        agentSettingsSelection: {
            get() {
                if (!this.scene?.data) return '__auto__';
                if (this.scene.data.agent_settings_opted_out) return '__opt_out__';
                if (this.scene.data.agent_settings_file) return this.scene.data.agent_settings_file;
                return '__auto__';
            },
            set(value) {
                // mutation happens in updateAgentSettings; this setter exists
                // so v-model is happy but we drive the actual update there
                // (which knows how to send the right payload).
                this._pendingAgentSettings = value;
            }
        },
        agentSettingsOptions() {
            const files = this.scene?.data?.agent_settings_files || [];
            const items = [
                { value: '__auto__', title: 'Auto-link (default)', props: { subtitle: 'Use agent-settings/agent-settings.json if present in the project folder. Replaces any current explicit link.' } },
                { value: '__opt_out__', title: 'None (opt out)', props: { subtitle: 'No per-scene agent overrides.' } },
            ];
            for (const f of files) {
                items.push({ value: f, title: f, props: { subtitle: 'Linked file in agent-settings/.' } });
            }
            return items;
        },
        visualStyleTemplates() {
            if(!this.templates || !this.templates.by_type.visual_style) return [{ value: null, title: 'Use Agent Default' }];
            let templates = Object.values(this.templates.by_type.visual_style)
                .filter((template) => template.visual_type === 'STYLE')
                .map((template) => {
                    return {
                        value: `${template.group}__${template.uid}`,
                        title: template.name,
                        props: { subtitle: template.description }
                    }
                });
            templates.unshift({ 
                value: null, 
                title: 'Use Agent Default', 
                props: { subtitle: 'Use the default art style from agent configuration.' } 
            });
            return templates;
        }
    },
    data() {
        return {
            MAX_CONTENT_WIDTH,
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
                visual_style_template: this.scene.data.visual_style_template,
                restore_from: this.scene.data.restore_from,
            }));
        },
        updateAgentSettings(value) {
            // Translate picker value into a backend payload. Server reads
            // presence-vs-absence of these keys (via pydantic
            // model_fields_set) to distinguish "explicit None = opt out"
            // from "absent = leave the link alone".
            const payload = {
                type: 'world_state_manager',
                action: 'update_scene_settings',
                experimental: this.scene.data.experimental,
                immutable_save: this.scene.data.immutable_save,
                writing_style_template: this.scene.data.writing_style_template,
                agent_persona_templates: this.scene.data.agent_persona_templates || {},
                visual_style_template: this.scene.data.visual_style_template,
                restore_from: this.scene.data.restore_from,
            };

            if (value === '__opt_out__') {
                payload.agent_settings_file = null;
            } else if (value === '__auto__') {
                payload.agent_settings_opted_out = false;
            } else {
                payload.agent_settings_file = value;
            }

            this.getWebsocket().send(JSON.stringify(payload));
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
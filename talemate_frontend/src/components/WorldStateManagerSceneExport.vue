<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
    <v-row>
        <v-col cols="12">
            <v-form class="mt-4" v-model="formIsValid" ref="form">
                <v-row>
                    <v-col cols="12" lg="6" xl="3">
                        <v-select
                            v-model="format"
                            :items="formats"
                            label="Export Format"
                        ></v-select>
                    </v-col>
                    <v-col cols="12" lg="6" xl="4">
                        <v-text-field
                            v-model="exportName"
                            :rules="[rules.required]"
                            label="Export Name"
                            hint="The name of the exported file."
                        ></v-text-field>
                    </v-col>
                </v-row>
                <v-row>
                    <v-col cols="12">
                        <v-checkbox
                            v-model="resetProgress"
                            label="Reset Progress"
                            messages="If checked, the progress of the scene will be reset. Clearing messages, choices and other stateful data."
                        ></v-checkbox>
                    </v-col>
                </v-row>
                <v-row v-if="format === 'talemate_complete'">
                    <v-col cols="12">
                        <v-card variant="outlined" class="pa-3">
                            <v-card-title class="text-subtitle-1">Include in Export</v-card-title>
                            <v-row>
                                <v-col cols="6" md="3">
                                    <v-checkbox
                                        v-model="includeAssets"
                                        label="Assets"
                                        hint="Images and TTS files"
                                    ></v-checkbox>
                                </v-col>
                                <v-col cols="6" md="3">
                                    <v-checkbox
                                        v-model="includeNodes"
                                        label="Nodes"
                                        hint="Custom node definitions"
                                    ></v-checkbox>
                                </v-col>
                                <v-col cols="6" md="3">
                                    <v-checkbox
                                        v-model="includeInfo"
                                        label="Info"
                                        hint="Voice library, modules"
                                    ></v-checkbox>
                                </v-col>
                                <v-col cols="6" md="3">
                                    <v-checkbox
                                        v-model="includeTemplates"
                                        label="Templates"
                                        hint="Custom Jinja2 templates"
                                    ></v-checkbox>
                                </v-col>
                            </v-row>
                        </v-card>
                    </v-col>
                </v-row>
            </v-form>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="primary" prepend-icon="mdi-export" @click="requestExport">Export</v-btn>
            </v-card-actions>
        </v-col>
    </v-row>
    </div>

</template>
<script>
import { MAX_CONTENT_WIDTH } from '@/constants';

export default {
    name: 'WorldStateManagerSceneExport',
    props: {
        scene: Object,
    },
    inject:[
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'setWaitingForInput',
        'requestSceneAssets',
    ],
    data() {
        return {
            MAX_CONTENT_WIDTH,
            formats: [
                { value: 'talemate', title: 'Talemate Scene (JSON only)' },
                { value: 'talemate_complete', title: 'Complete Scene Package (ZIP)' },
            ],
            format: 'talemate_complete',
            resetProgress: true,
            exportName: '',
            formIsValid: false,
            includeAssets: true,
            includeNodes: true,
            includeInfo: true,
            includeTemplates: true,
            rules: {
                required: value => !!value || 'Required.'
            }
        }
    },
    methods: {
        requestExport() {

            this.$refs.form.validate();

            if(!this.formIsValid) {
                return;
            }

            const exportOptions = {
                type: 'world_state_manager',
                action: 'export_scene',
                format: this.format,
                reset_progress: this.resetProgress,
                name: this.exportName,
            };

            // Add complete export options if selected
            if (this.format === 'talemate_complete') {
                exportOptions.include_assets = this.includeAssets;
                exportOptions.include_nodes = this.includeNodes;
                exportOptions.include_info = this.includeInfo;
                exportOptions.include_templates = this.includeTemplates;
            }

            this.getWebsocket().send(JSON.stringify(exportOptions));
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'scene_exported') {
                const scene_b64 = message.data;
                const format = message.format || 'talemate';
                const fileExtension = message.file_extension || 'json';
                
                // prepare data url for download
                const mimeType = fileExtension === 'zip' ? 'application/zip' : 'application/json';
                const data = `data:${mimeType};base64,${scene_b64}`;
                
                // trigger download
                const a = document.createElement('a');
                a.href = data;
                a.download = `${this.exportName}.${fileExtension}`;
                a.click();
                
                // Show success message
                this.$emit('show-message', {
                    message: `Scene exported successfully as ${this.exportName}.${fileExtension}`,
                    type: 'success'
                });
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
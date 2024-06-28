<template>
    <v-card>
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
        </v-form>
        <v-card-actions>
            <v-spacer></v-spacer>
            <v-btn color="primary" prepend-icon="mdi-export" @click="requestExport">Export</v-btn>
        </v-card-actions>
    </v-card>

</template>
<script>

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
            formats: [
                { value: 'talemate', title: 'Talemate Scene' },
            ],
            format: 'talemate',
            resetProgress: true,
            exportName: '',
            formIsValid: false,
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

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'export_scene',
                format: this.format,
                reset_progress: this.resetProgress,
                name: this.exportName,
            }));
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'scene_exported') {
                const scene_b64 = message.data;
                // prepare data url for download
                const data = `data:application/octet-stream;base64,${scene_b64}`;
                // trigger download
                const a = document.createElement('a');
                a.href = data;
                a.download = `${this.exportName}.json`;
                a.click();
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
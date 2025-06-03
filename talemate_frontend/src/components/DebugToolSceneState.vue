<template>
    <v-dialog v-model="dialog" style="max-width:2048px">
        <v-card>
            <v-card-title>
                <span class="headline">Scene State Editor</span>
            </v-card-title>
            <v-card-text>
                <v-alert type="warning" class="text-caption" variant="tonal">
                    Editing the scene state through this editor can ABSOLUTELY brick your game. Be careful. However as long as you do not save the scene afterwards, you can always reload the game to get back to the original state.
                </v-alert>
                <Codemirror
                    v-model="sceneStateJSON"
                    :extensions="extensions"
                    :style="promptEditorStyle"
                ></Codemirror>
            </v-card-text>
            <v-card-actions>
                <v-btn @click="close" color="cancel">Close</v-btn>
                <v-spacer></v-spacer>
                <v-btn @click="updateSceneState" color="primary" :disabled="busy">Update</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>

import { Codemirror } from 'vue-codemirror'
import { json } from '@codemirror/lang-json'
import { oneDark } from '@codemirror/theme-one-dark'
import { EditorView } from '@codemirror/view'

export default {
    name: 'DebugToolSceneState',
    components: {
        Codemirror,
    },
    data() {
        return {
            sceneState: null,
            sceneStateJSON: null,
            dialog: false,
            busy: false,
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'unregisterMessageHandler', 'setWaitingForInput'],
    methods: {
        open() {
            this.dialog = true;
            this.getSceneState();
        },
        close() {
            this.dialog = false;
        },

        getSceneState() {
            this.getWebsocket().send(JSON.stringify({
                type: 'devtools',
                action: 'get_scene_state',
            }));
        },

        updateSceneState() {
            self.busy = true;
            const data = JSON.parse(this.sceneStateJSON);
            this.getWebsocket().send(JSON.stringify({
                type: 'devtools',
                action: 'update_scene_state',
                state: data,
            }));
        },

        handleMessage(data) {
            if (data.type !== 'devtools') {
                return;
            }
            if(data.action === 'scene_state') {
                this.sceneState = data.data;
                this.sceneStateJSON = JSON.stringify(data.data, null, 4);
            } else if(data.action === 'operation_done') {
                this.busy = false;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
    setup() {

        const extensions = [
            json(),
            oneDark,
            EditorView.lineWrapping
        ];

        const promptEditorStyle = {
            maxHeight: "1440px",
            minHeight: "640px",
        }

        return {
            extensions,
            promptEditorStyle,
        }
    }
}

</script>

<style scoped>

pre.game-state {
    white-space: pre-wrap;
}

</style>
<template>
    <v-menu :disabled="appBusy">
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-1" v-bind="props" :disabled="appBusy" color="primary" icon variant="text">
                <v-icon>mdi-content-save</v-icon>
            </v-btn>
        </template>
        <v-list>
            <v-list-subheader>Save</v-list-subheader>
            <v-list-item @click="save" prepend-icon="mdi-content-save" :disabled="!canSaveToCurrentFile">
                <v-list-item-title>Save</v-list-item-title>
                <v-list-item-subtitle>Save the current scene</v-list-item-subtitle>
            </v-list-item>
            <v-list-item @click="() => { saveAs() }" prepend-icon="mdi-content-save-all">
                <v-list-item-title>Save As</v-list-item-title>
                <v-list-item-subtitle>Save the current scene as a new scene</v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>

    <RequestInput ref="saveAsInput" title="Save As"
        :instructions="'Enter a name for the new scene'"
        input-type="text" icon="mdi-content-save-all" :size="750" @continue="saveAs" />
</template>

<script>

import RequestInput from './RequestInput.vue';

export default {
    name: 'SceneToolsSave',
    components: {
        RequestInput,
    },
    props: {
        appBusy: Boolean,
        scene: Object,
    },
    inject: ['getWebsocket'],
    computed: {
        canSaveToCurrentFile() {
            return this.scene?.data?.filename && !this.scene?.data?.immutable_save;
        },
    },
    methods: {

        save() {
            if(!this.canSaveToCurrentFile) {
                this.saveAs();
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "save_scene",
                project_name: this.scene?.data?.project_name,
            }));
        },

        saveAs(saveName=null) {
            if (saveName === null) {
                this.$refs.saveAsInput.openDialog();
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "save_scene",
                save_as: saveName,
                project_name: this.scene?.data?.project_name,
            }));
        }


    }
}

</script>
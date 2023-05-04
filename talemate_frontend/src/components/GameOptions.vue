<template>

    <v-list-subheader class="text-uppercase">
        <v-icon class="mr-1">mdi-cogs</v-icon>Options
        <v-btn-toggle v-model="selected_options" density="compact">
            <v-btn value="automated_actions"><v-icon>mdi-brightness-auto</v-icon></v-btn>
        </v-btn-toggle>
    </v-list-subheader>

    <v-card v-if="selected_options==='automated_actions'">
        <v-card-title class="text-subtitle-2"><v-icon>mdi-brightness-auto</v-icon> Automatic actions</v-card-title>
        <v-card-text>
            <div v-for="(value, action) in scene_config.automated_actions" :key="action">
                <v-switch v-model="scene_config.automated_actions[action]" :label="cleanLabel(action)" class="ml-2 text-caption" density="compact" @update:model-value="saveSceneConfig()"></v-switch>
            </div>
        </v-card-text>
    </v-card>

</template>

<script>
export default {
    name: 'GameOptions',
    data() {
        return {
            selected_options: null,
            scene_config: {
                automated_actions: {
                    world_state: true,
                    director: true,        
                }
            }
        }
    },

    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput'],

    methods: {
        cleanLabel(label) {
            return label.replace(/_/g, ' ');
        },
        saveSceneConfig() {
            this.getWebsocket().send(JSON.stringify({
                type: 'scene_config',
                scene_config: this.scene_config,
            }));
        },
        handleMessage(data) {
            if(data.type === 'scene_status') {
                this.scene_config = data.data.scene_config;
            }
        },
    },

    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>

</style>
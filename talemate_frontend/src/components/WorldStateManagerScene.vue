<template>
    <div v-if="scene !== null">
        <v-card>
            <v-card-title>
                {{ title }}
                <div class="text-muted text-caption">
                    {{ scene.context }}
                </div>
            </v-card-title>
            <v-card-text>
                <v-tabs v-model="page" color="primary" density="compact">
                    <v-tab value="outline">
                        <v-icon size="small" class="mr-1">mdi-script-text</v-icon>
                        Outline
                    </v-tab>
                    <v-tab value="messages">
                        <v-icon size="small" class="mr-1">mdi-message-text</v-icon>
                        Messages
                    </v-tab>
                    <v-tab value="time">
                        <v-icon size="small" class="mr-1">mdi-clock</v-icon>
                        Time
                    </v-tab>
                    <v-tab value="director">
                        <v-icon size="small" class="mr-1">mdi-dice-multiple</v-icon>
                        Game Director
                    </v-tab>
                    <v-tab>
                        <v-icon size="small" class="mr-1">mdi-cogs</v-icon>
                        Settings
                    </v-tab>
                </v-tabs>
                <v-divider></v-divider>
                <v-window v-model="page">
                    <v-window-item value="outline">
                        <WorldStateManagerSceneOutline 
                            :app-config="appConfig"
                            :immutableScene="scene">
                        </WorldStateManagerSceneOutline>
                    </v-window-item>
                </v-window> 
            </v-card-text>
        </v-card>
    </div>
    <div v-else>

    </div>
</template>
<script>

import WorldStateManagerSceneOutline from './WorldStateManagerSceneOutline.vue';

export default {
    name: "WorldStateManagerScene",
    components: {
        WorldStateManagerSceneOutline,
    },
    props: {
        scene: Object,
        appConfig: Object,
    },
    inject:[
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'setWaitingForInput',
        'requestSceneAssets',
    ],
    computed: {
        title() {
            if(!this.scene) {
                return "No Scene Selected";
            }
            return this.scene.title || this.scene.name;
        },
    },
    data() {
        return {
            selected: null,
            page: 'outline'
        }
    },
    methods:{
        handleMessage(message) {
            console.log("WorldStateManagerScene handleMessage", message);
        }
    },
    mounted(){
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted(){
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>
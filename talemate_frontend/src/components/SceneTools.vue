<template>
    <!-- Hotbuttons Section -->
    <div class="hotbuttons-section">


        <!-- Section 0: Loading indicator and rerun tool -->

        <v-card class="hotbuttons-section-1">
            <v-card-actions>
                <v-progress-circular class="ml-1 mr-3" size="24" v-if="!isWaitingForInput()" indeterminate
                    color="primary"></v-progress-circular>                
                <v-icon class="ml-1 mr-3" v-else-if="isWaitingForInput()">mdi-keyboard</v-icon>
                <v-icon class="ml-1 mr-3" v-else>mdi-circle-outline</v-icon>

                <v-divider vertical></v-divider>


                <v-tooltip v-if="isEnvironment('scene')" :disabled="isInputDisabled()" location="top"
                    text="Redo most recent AI message">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!rerun')" color="primary" icon>
                            <v-icon>mdi-refresh</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-tooltip v-if="isEnvironment('scene')" :disabled="isInputDisabled()" location="top"
                    text="Redo most recent AI message (Nuke Option - use this to attempt to break out of repetition)">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!rerun:0.5')" color="primary" icon>
                            <v-icon>mdi-nuke</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>


                <v-tooltip v-if="commandActive" location="top"
                    text="Abort / end action.">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mr-3" v-bind="props" v-on="on" :disabled="!isWaitingForInput()"
                            @click="sendHotButtonMessage('!abort')" color="primary" icon>
                            <v-icon>mdi-cancel</v-icon>
                            
                        </v-btn>
                        <v-label v-text="this.commandName" class="mr-3 ml-3"></v-label>
                    </template>
                </v-tooltip>
            </v-card-actions>
        </v-card>


        <!-- Section 1: Game Interaction -->
        <v-card class="hotbuttons-section-1" v-if="isEnvironment('scene')">
            <v-card-actions>
                <v-tooltip :disabled="isInputDisabled()" location="top" text="Narrate: Progress Story">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!narrate_progress')" color="primary" icon>
                            <v-icon>mdi-script-text-play</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>
                <v-tooltip :disabled="isInputDisabled()" location="top" text="Narrate: Scene">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!narrate')" color="primary" icon>
                            <v-icon>mdi-script-text</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>
                <v-tooltip :disabled="isInputDisabled()" location="top" text="Narrate: Character">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!narrate_c')" color="primary" icon>
                            <v-icon>mdi-account-voice</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>
                <v-tooltip :disabled="isInputDisabled()" location="top" text="Narrate: Query">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!narrate_q')" color="primary" icon>
                            <v-icon>mdi-crystal-ball</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>
                <v-menu>
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" :disabled="isInputDisabled()" color="primary" icon>
                            <v-icon>mdi-clock</v-icon>
                        </v-btn>
                    </template>
                    <v-list>
                        <v-list-subheader>Advance Time</v-list-subheader>
                        <v-list-item v-for="(option, index) in advanceTimeOptions" :key="index"
                            @click="sendHotButtonMessage('!advance_time:' + option.value)">
                            <v-list-item-title>{{ option.title }}</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </v-menu>
                <v-divider vertical></v-divider>
                <v-tooltip :disabled="isInputDisabled()" location="top" text="Direct a character">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!director')" color="primary" icon>
                            <v-icon>mdi-bullhorn</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>
            </v-card-actions>
        </v-card>

        <!-- Section 2: Tools -->
        <v-card class="hotbuttons-section-2">
            <v-card-actions>

                <v-tooltip :disabled="isInputDisabled()" location="top" text="Save">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!save')" color="primary" icon>
                            <v-icon>mdi-content-save</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-tooltip :disabled="isInputDisabled()" location="top" text="Save As">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!save_as')" color="primary" icon>
                            <v-icon>mdi-content-save-all</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-tooltip v-if="isEnvironment('scene')" :disabled="isInputDisabled()" location="top" text="Switch to creative mode">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!setenv_creative')" color="primary" icon>
                            <v-icon>mdi-palette-outline</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-tooltip v-else-if="isEnvironment('creative')" :disabled="isInputDisabled()" location="top" text="Switch to game mode">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" v-on="on" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!setenv_scene')" color="primary" icon>
                            <v-icon>mdi-gamepad-square</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

            </v-card-actions>
        </v-card>

    </div>
    
</template>


<script>

export default {

    name: 'SceneTools',
    data() {
        return {
            commandActive: false,
            commandName: null,

            advanceTimeOptions: [
                {"value" : "P10Y", "title": "10 years"},
                {"value" : "P5Y", "title": "5 years"},
                {"value" : "P1Y", "title": "1 year"},
                {"value" : "P6M", "title": "6 months"},
                {"value" : "P3M", "title": "3 months"},
                {"value" : "P1M", "title": "1 month"},
                {"value" : "P7D:1 Week later", "title": "1 week"},
                {"value" : "P3D", "title": "3 days"},
                {"value" : "P1D", "title": "1 day"},
                {"value" : "PT8H", "title": "8 hours"},
                {"value" : "PT4H", "title": "4 hours"},
                {"value" : "PT1H", "title": "1 hour"},
                {"value" : "PT30M", "title": "30 minutes"},
                {"value" : "PT15M", "title": "15 minutes"}
            ],
        }
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'isInputDisabled',
        'setInputDisabled',
        'isWaitingForInput',
        'scene',
        'creativeEditor',
    ],
    methods: {


        isEnvironment(typ) {
            return this.scene().environment == typ;
        },

        sendHotButtonMessage(message) {
            if (message == "!abort" || !this.isInputDisabled()) {
                this.getWebsocket().send(JSON.stringify({ type: 'interact', text: message }));
                this.setInputDisabled(true);
            }
        },

        handleMessage(data) {

            if (data.type == "command_status") {
                if(data.status == "started") {
                    this.commandActive = true;
                    this.commandName = data.name;
                } else {
                    this.commandActive = false;
                    this.commandName = null;
                }
            }
        }
    },
    mounted() {
        console.log("Websocket", this.getWebsocket()); // Check if websocket is available
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}

</script>

<style scoped>
.hotbuttons-section {
    display: flex;
    justify-content: flex-start;
    margin-bottom: 10px;
}

.hotbuttons-section-1,
.hotbuttons-section-2,
.hotbuttons-section-3 {
    display: flex;
    align-items: center;
    margin-right: 20px;
}
</style>
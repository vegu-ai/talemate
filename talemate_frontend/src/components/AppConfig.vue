<template>
    <v-dialog v-model="dialog" scrollable max-width="50%">
        <v-card v-if="app_config !== null">

            <v-tabs color="primary" v-model="tab">
                <v-tab value="game">
                    <v-icon start>mdi-gamepad-square</v-icon>
                    Game
                </v-tab>
                <v-tab value="creator">
                    <v-icon start>mdi-palette-outline</v-icon>
                    Creator
                </v-tab>
            </v-tabs>
            <v-window v-model="tab">
                <v-window-item value="game">
                    <v-card flat>
                        <v-card-title>
                            Default player character
                            <v-tooltip location="top" max-width="500" text="This will be default player character that will be added to a game if the game does not come with a defined player character. Essentially this is relevant for when you load character-cards that aren't in the talemate scene format.">
                                <template v-slot:activator="{ props }">
                                    <v-icon size="x-small" v-bind="props" v-on="on">mdi-help</v-icon>
                                </template>
                            </v-tooltip>
                        </v-card-title>
                        <v-card-text>
                            <v-row>
                                <v-col cols="6">
                                    <v-text-field v-model="app_config.game.default_player_character.name" label="Name"></v-text-field>
                                </v-col>
                                <v-col cols="6">
                                    <v-text-field v-model="app_config.game.default_player_character.gender" label="Gender"></v-text-field>
                                </v-col>
                            </v-row>
                            <v-row>
                                <v-col>
                                    <v-textarea v-model="app_config.game.default_player_character.description" auto-grow label="Description"></v-textarea>
                                </v-col>
                                <v-col>
                                    <v-color-picker v-model="app_config.game.default_player_character.color" hide-inputs  label="Color" elevation="0"></v-color-picker>

                                </v-col>

                            </v-row>
                        </v-card-text>
                    </v-card>
                </v-window-item>
                <v-window-item value="creator">
                    <v-card flat>
                        <v-card-title>
                            Content context
                            <v-tooltip location="top" max-width="500" text="Available choices when generating characters or scenarios within talemate.">
                                <template v-slot:activator="{ props }">
                                    <v-icon size="x-small" v-bind="props" v-on="on">mdi-help</v-icon>
                                </template>
                            </v-tooltip>
                        </v-card-title>
                        <v-card-text style="max-height:600px; overflow-y:scroll;">
                            <v-list density="compact">
                                <v-list-item v-for="(value, index) in app_config.creator.content_context" :key="index">
                                    <v-list-item-title><v-icon color="red">mdi-delete</v-icon>{{ value }}</v-list-item-title>
                                </v-list-item>
                            </v-list>
                            <v-text-field v-model="content_context_input" label="Add content context" @keyup.enter="app_config.creator.content_context.push(content_context_input); app_config.creator.content_context_input = ''"></v-text-field>
                        </v-card-text>
                    </v-card>
                </v-window-item>
            </v-window>
            <v-card-actions>
                <v-btn color="primary" text @click="saveConfig">Save</v-btn>
            </v-card-actions>
        </v-card>
        <v-card v-else>
            <v-card-title>
                <span class="headline">Configuration</span>
            </v-card-title>
            <v-card-text>
                <v-progress-circular indeterminate color="primary" size="20"></v-progress-circular>
            </v-card-text>
        </v-card>
    </v-dialog> 
</template>
<script>

export default {
    name: 'AppConfig',
    data() {
        return {
            tab: 'game',
            dialog: false,
            app_config: null,
            content_context_input: '',
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'requestSceneAssets', 'requestAppConfig'],

    methods: {
        show() {
            this.requestAppConfig();
            this.dialog = true;

        },
        exit() {
            this.dialog = false
        },

        handleMessage(message) {
            if (message.type == "app_config") {
                this.app_config = message.data;
                return;
            }

            if (message.type == 'config') {
                if(message.action == 'save_complete') {
                    this.exit();
                }
            }
        },

        sendRequest(data) {
            data.type = 'config';
            this.getWebsocket().send(JSON.stringify(data));
        },

        saveConfig() {
            this.sendRequest({
                action: 'save',
                config: this.app_config,
            })
        },

    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },

}

</script>

<style scoped>
</style>
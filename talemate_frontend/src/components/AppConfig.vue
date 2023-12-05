<template>
    <v-dialog v-model="dialog" scrollable max-width="960px">
        <v-card v-if="app_config !== null">
            <v-card-title><v-icon class="mr-1">mdi-cog</v-icon>Settings</v-card-title>
            <v-tabs color="primary" v-model="tab">
                <v-tab value="game">
                    <v-icon start>mdi-gamepad-square</v-icon>
                    Game
                </v-tab>
                <v-tab value="application">
                    <v-icon start>mdi-application</v-icon>
                    Application
                </v-tab>
                <v-tab value="creator">
                    <v-icon start>mdi-palette-outline</v-icon>
                    Creator
                </v-tab>
            </v-tabs>
            <v-window v-model="tab">

                <!-- GAME -->

                <v-window-item value="game">
                    <v-card flat>
                        <v-card-text>
                            <v-row>
                                <v-col cols="4">
                                    <v-list>
                                        <v-list-item @click="gamePageSelected=item.value" :prepend-icon="item.icon"  v-for="(item, index) in navigation.game" :key="index">
                                            <v-list-item-title>{{ item.title }}</v-list-item-title>
                                        </v-list-item>
                                    </v-list>
                                </v-col>
                                <v-col cols="8">
                                    <div v-if="gamePageSelected === 'character'">
                                        <v-alert color="white" variant="text" icon="mdi-human-edit" density="compact">
                                            <v-alert-title>Default player character</v-alert-title>
                                            <div class="text-grey">
                                                This will be default player character that will be added to a game if the game does not come with a defined player character. Essentially this is relevant for when you load character-cards that aren't in the talemate scene format.                     

                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="6">
                                                <v-text-field v-model="app_config.game.default_player_character.name"
                                                    label="Name"></v-text-field>
                                            </v-col>
                                            <v-col cols="6">
                                                <v-text-field v-model="app_config.game.default_player_character.gender"
                                                    label="Gender"></v-text-field>
                                            </v-col>
                                        </v-row>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-textarea v-model="app_config.game.default_player_character.description"
                                                    auto-grow label="Description"></v-textarea>
                                            </v-col>
                                        </v-row>
                                    </div>
                                </v-col>
                            </v-row>
                        </v-card-text>
                    </v-card>
                </v-window-item>

                <!-- APPLICATION -->

                <v-window-item value="application">
                    <v-card flat>
                        <v-card-text>
                            <v-row>
                                <v-col cols="4">
                                    <v-list>
                                        <v-list-subheader>Third Party APIs</v-list-subheader>
                                        <v-list-item @click="applicationPageSelected=item.value" :prepend-icon="item.icon"  v-for="(item, index) in navigation.application" :key="index">
                                            <v-list-item-title>{{ item.title }}</v-list-item-title>
                                        </v-list-item>
                                    </v-list>
                                </v-col>
                                <v-col cols="8">

                                    <!-- OPENAI API -->
                                    <div v-if="applicationPageSelected === 'openai_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>OpenAI</v-alert-title>
                                            <div class="text-grey">
                                                Configure your OpenAI API key here. You can get one from <a href="https://platform.openai.com/" target="_blank">https://platform.openai.com/</a> 
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.openai.api_key"
                                                    label="OpenAI API Key"></v-text-field>
                                            </v-col>
                                        </v-row>
                                    </div>

                                    <!-- ELEVENLABS API -->
                                    <div v-if="applicationPageSelected === 'elevenlabs_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>ElevenLabs</v-alert-title>
                                            <div class="text-grey">
                                                <p class="mb-1">Generate realistic speech with the most advanced AI voice model ever.</p>
                                                Configure your ElevenLabs API key here. You can get one from <a href="https://elevenlabs.io/?from=partnerewing2048" target="_blank">https://elevenlabs.io</a> <span class="text-caption">(affiliate link)</span>
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.elevenlabs.api_key"
                                                    label="ElevenLabs API Key"></v-text-field>
                                            </v-col>
                                        </v-row>
                                    </div>

                                    <!-- COQUI API -->
                                    <div v-if="applicationPageSelected === 'coqui_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>Coqui Studio</v-alert-title>
                                            <div class="text-grey">
                                                <p class="mb-1">Realistic, emotive text-to-speech through generative AI.</p>
                                                Configure your Coqui API key here. You can get one from <a href="https://app.coqui.ai/account" target="_blank">https://app.coqui.ai/account</a> 
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.coqui.api_key"
                                                    label="Coqui API Key"></v-text-field>
                                            </v-col>
                                        </v-row>
                                    </div>

                                    <!-- RUNPOD API -->
                                    <div v-if="applicationPageSelected === 'runpod_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>RunPod</v-alert-title>
                                            <div class="text-grey">
                                                <p class="mb-1">Launch a GPU instance in seconds.</p>
                                                Configure your RunPod API key here. You can get one from <a href="https://runpod.io?ref=gma8kdu0" target="_blank">https://runpod.io/</a>  <span class="text-caption">(affiliate link)</span>
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.runpod.api_key"
                                                    label="RunPod API Key"></v-text-field>
                                            </v-col>
                                        </v-row>
                                    </div>

                                </v-col>
                            </v-row>
                        </v-card-text>
                    </v-card>
                </v-window-item>

                <!-- CREATOR -->

                <v-window-item value="creator">
                    <v-card flat>
                        <v-card-text>
                            <v-row>
                                <v-col cols="4">
                                    <v-list>
                                        <v-list-item @click="creatorPageSelected=item.value" :prepend-icon="item.icon"  v-for="(item, index) in navigation.creator" :key="index">
                                            <v-list-item-title>{{ item.title }}</v-list-item-title>
                                        </v-list-item>
                                    </v-list>
                                </v-col>
                                <v-col cols="8">
                                    <div v-if="creatorPageSelected === 'content_context'">
                                        <!-- Content for Content context will go here -->
                                        <v-alert color="white" variant="text" icon="mdi-cube-scan" density="compact">
                                            <v-alert-title>Content context</v-alert-title>
                                            <div class="text-grey">
                                                Available content-context choices when generating characters or scenarios. This can strongly influence the content that is generated.
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-list density="compact">
                                                    <v-list-item v-for="(value, index) in app_config.creator.content_context" :key="index">
                                                        <v-list-item-title><v-icon color="red" class="mr-2" @click="contentContextRemove(index)">mdi-delete</v-icon>{{ value }}</v-list-item-title>
                                                    </v-list-item>
                                                </v-list>
                                                <v-divider></v-divider>
                                                <v-text-field v-model="content_context_input" label="Add content context (Press enter to add)"
                                                    @keyup.enter="app_config.creator.content_context.push(content_context_input); content_context_input = ''"></v-text-field>
                                            </v-col>
                                        </v-row>

                                        
                                    </div>
                                </v-col>
                            </v-row>
                        </v-card-text>
                    </v-card>
                </v-window-item>
            </v-window>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="primary" text @click="saveConfig" prepend-icon="mdi-check-circle-outline">Save</v-btn>
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
            navigation: {
                game: [
                    {title: 'Default Character', icon: 'mdi-human-edit', value: 'character'},
                ],
                application: [
                    {title: 'OpenAI', icon: 'mdi-api', value: 'openai_api'},
                    {title: 'ElevenLabs', icon: 'mdi-api', value: 'elevenlabs_api'},
                    {title: 'Coqui Studio', icon: 'mdi-api', value: 'coqui_api'},
                    {title: 'RunPod', icon: 'mdi-api', value: 'runpod_api'},
                ],
                creator: [
                    {title: 'Content Context', icon: 'mdi-cube-scan', value: 'content_context'},
                ]
            },
            gamePageSelected: 'character',
            applicationPageSelected: 'openai_api',
            creatorPageSelected: 'content_context',
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

        contentContextRemove(index) {
            this.app_config.creator.content_context.splice(index, 1);
        },

        handleMessage(message) {
            if (message.type == "app_config") {
                this.app_config = message.data;
                return;
            }

            if (message.type == 'config') {
                if (message.action == 'save_complete') {
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

<style scoped></style>
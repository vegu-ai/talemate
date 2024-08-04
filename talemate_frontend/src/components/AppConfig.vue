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
                <v-tab value="presets">
                    <v-icon start>mdi-tune</v-icon>
                    Presets
                </v-tab>
                <v-tab value="creator">
                    <v-icon start>mdi-palette-outline</v-icon>
                    Creator
                </v-tab>
            </v-tabs>
            <v-divider></v-divider>
            <v-window v-model="tab">

                <!-- GAME -->

                <v-window-item value="game">
                    <v-card flat>
                        <v-card-text>
                            <v-row>
                                <v-col cols="4">
                                    <v-tabs v-model="gamePageSelected" color="primary" direction="vertical">
                                        <v-tab v-for="(item, index) in navigation.game" :key="index" :value="item.value">
                                            <v-icon class="mr-1">{{ item.icon }}</v-icon>
                                            {{ item.title }}
                                        </v-tab>
                                    </v-tabs>
                                </v-col>
                                <v-col cols="8">
                                    <div v-if="gamePageSelected === 'general'">
                                        <v-alert color="white" variant="text" icon="mdi-cog" density="compact">
                                            <v-alert-title>General</v-alert-title>
                                            <div class="text-grey">
                                                General game settings.
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-checkbox v-model="app_config.game.general.auto_save" label="Auto save" messages="Automatically save after each game-loop"></v-checkbox>
                                                <v-checkbox v-model="app_config.game.general.auto_progress" label="Auto progress" messages="AI automatically progresses after player turn."></v-checkbox>
                                            </v-col>
                                        </v-row>
                                        <v-row>
                                            <v-col cols="6">
                                                <v-text-field v-model="app_config.game.general.max_backscroll" type="number" label="Max backscroll" messages="Maximum number of messages to keep in the scene backscroll"></v-text-field>
                                            </v-col>
                                        </v-row>        
                                    </div>
                                    <div v-else-if="gamePageSelected === 'character'">
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

                                        <v-tabs v-model="applicationPageSelected" color="primary" direction="vertical" density="compact">
                                            <v-tab v-for="(item, index) in navigation.application" :key="index" :value="item.value">
                                                <v-icon class="mr-1">{{ item.icon }}</v-icon>
                                                {{ item.title }}
                                            </v-tab>
                                        </v-tabs>
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

                                    <!-- MISTRAL.AI API -->
                                    <div v-if="applicationPageSelected === 'mistralai_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>mistral.ai</v-alert-title>
                                            <div class="text-grey">
                                                Configure your mistral.ai API key here. You can get one from <a href="https://console.mistral.ai/api-keys/" target="_blank">https://console.mistral.ai/api-keys/</a> 
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.mistralai.api_key"
                                                    label="mistral.ai API Key"></v-text-field>
                                            </v-col>
                                        </v-row>
                                    </div>

                                    <!-- ANTHROPIC API -->
                                    <div v-if="applicationPageSelected === 'anthropic_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>Anthropic</v-alert-title>
                                            <div class="text-grey">
                                                Configure your Anthropic API key here. You can get one from <a href="https://console.anthropic.com/settings/keys" target="_blank">https://console.anthropic.com/settings/keys</a> 
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.anthropic.api_key"
                                                    label="Anthropic API Key"></v-text-field>
                                            </v-col>
                                        </v-row>
                                    </div>

                                    <!-- COHERE API -->
                                    <div v-if="applicationPageSelected === 'cohere_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>Cohere</v-alert-title>
                                            <div class="text-grey">
                                                Configure your Cohere API key here. You can get one from <a href="https://dashboard.cohere.com/api-keys" target="_blank">https://dashboard.cohere.com/api-keys</a> 
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.cohere.api_key"
                                                    label="Cohere API Key"></v-text-field>
                                            </v-col>
                                        </v-row>
                                    </div>

                                    <!-- GROQ API -->
                                    <div v-if="applicationPageSelected === 'groq_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>groq</v-alert-title>
                                            <div class="text-grey">
                                                Configure your GROQ API key here. You can get one from <a href="https://console.groq.com/keys" target="_blank">https://console.groq.com/keys</a> 
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.groq.api_key"
                                                    label="GROQ API Key"></v-text-field>
                                            </v-col>
                                        </v-row>
                                    </div>

                                    <!-- GOOGLE API
                                         THis adds fields for 
                                            gcloud_credentials_path
                                            gcloud_project_id
                                            gcloud_location
                                    -->

                                    <div v-if="applicationPageSelected === 'google_api'">
                                        <v-alert color="white" variant="text" icon="mdi-google-cloud" density="compact">
                                            <v-alert-title>Google Cloud</v-alert-title>
                                            <div class="text-grey">
                                                In order for you to use Google Cloud services like the vertexi ai api for Gemini inference you will need to set up a Google Cloud project and credentials.
                                                
                                                Please follow the instructions <a href="https://cloud.google.com/vertex-ai/docs/start/client-libraries">here</a> and then fill in the fields below.
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field v-model="app_config.google.gcloud_credentials_path"
                                                    label="Google Cloud Credentials Path" messages="This should be a path to the credentials JSON file you downloaded through the setup above. This path needs to be accessible by the computer that is running the Talemate backend. If you are running Talemate on a server, you can upload the file to the server and the path should be the path to the file on the server."></v-text-field>
                                            </v-col>
                                            <v-col cols="6">
                                                <v-combobox v-model="app_config.google.gcloud_location"
                                                    label="Google Cloud Location" :items="googleCloudLocations" messages="Pick something close to you" :return-object="false"></v-combobox>
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

                <!-- PRESETS -->

                <v-window-item value="presets">
                    <AppConfigPresets 
                    ref="presets"
                    :immutable-config="app_config" 
                    :agentStatus="agentStatus"
                    :sceneActive="sceneActive"
                    ></AppConfigPresets>
                </v-window-item>

                <!-- CREATOR -->

                <v-window-item value="creator">
                    <v-card flat>
                        <v-card-text>
                            <v-row>
                                <v-col cols="4">
                                    <v-tabs v-model="creatorPageSelected" color="primary" direction="vertical">
                                        <v-tab v-for="(item, index) in navigation.creator" :key="index" :value="item.value">
                                            <v-icon class="mr-1">{{ item.icon }}</v-icon>
                                            {{ item.title }}
                                        </v-tab>
                                    </v-tabs>
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
                                                        <v-list-item-title><v-icon color="red-darken-1" class="mr-2" @click="contentContextRemove(index)">mdi-close-box-outline</v-icon>{{ value }}</v-list-item-title>
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
                <v-progress-circular indeterminate="disable-shrink" color="primary" size="20"></v-progress-circular>
            </v-card-text>
        </v-card>
    </v-dialog>
</template>
<script>

import AppConfigPresets from './AppConfigPresets.vue';

export default {
    name: 'AppConfig',
    components: {
        AppConfigPresets,
    },
    props: {
        agentStatus: Object,
        sceneActive: Boolean,
    },
    data() {
        return {
            tab: 'game',
            dialog: false,
            app_config: null,
            content_context_input: '',
            navigation: {
                game: [
                    {title: 'General', icon: 'mdi-cog', value: 'general'},
                    {title: 'Default Character', icon: 'mdi-human-edit', value: 'character'},
                ],
                application: [
                    {title: 'OpenAI', icon: 'mdi-api', value: 'openai_api'},
                    {title: 'mistral.ai', icon: 'mdi-api', value: 'mistralai_api'},
                    {title: 'Anthropic', icon: 'mdi-api', value: 'anthropic_api'},
                    {title: 'Cohere', icon: 'mdi-api', value: 'cohere_api'},
                    {title: 'groq', icon: 'mdi-api', value: 'groq_api'},
                    {title: 'Google Cloud', icon: 'mdi-google-cloud', value: 'google_api'},
                    {title: 'ElevenLabs', icon: 'mdi-api', value: 'elevenlabs_api'},
                    {title: 'RunPod', icon: 'mdi-api', value: 'runpod_api'},
                ],
                creator: [
                    {title: 'Content Context', icon: 'mdi-cube-scan', value: 'content_context'},
                ]
            },
            gamePageSelected: 'general',
            applicationPageSelected: 'openai_api',
            creatorPageSelected: 'content_context',
            googleCloudLocations: [
                {"value": 'us-central1', "title": 'US Central - Iowa'},
                {"value": 'us-west4', "title": 'US West 4 - Las Vegas'},
                {"value": 'us-east1', "title": 'US East 1 - South Carolina'},
                {"value": 'us-east4', "title": 'US East 4 - Northern Virginia'},
                {"value": 'us-west1', "title": 'US West 1 - Oregon'},
                {"value": 'northamerica-northeast1', "title": 'North America Northeast 1 - Montreal'},
                {"value": 'southamerica-east1', "title": 'South America East 1 - Sao Paulo'},
                {"value": 'europe-west1', "title": 'Europe West 1 - Belgium'},
                {"value": 'europe-north1', "title": 'Europe North 1 - Finland'},
                {"value": 'europe-west3', "title": 'Europe West 3 - Frankfurt'},
                {"value": 'europe-west2', "title": 'Europe West 2 - London'},
                {"value": 'europe-southwest1', "title": 'Europe Southwest 1 - Zurich'},
                {"value": 'europe-west8', "title": 'Europe West 8 - Netherlands'},
                {"value": 'europe-west4', "title": 'Europe West 4 - London'},
                {"value": 'europe-west9', "title": 'Europe West 9 - Stockholm'},
                {"value": 'europe-central2', "title": 'Europe Central 2 - Warsaw'},
                {"value": 'europe-west6', "title": 'Europe West 6 - Zurich'},
                {"value": 'asia-east1', "title": 'Asia East 1 - Taiwan'},
                {"value": 'asia-east2', "title": 'Asia East 2 - Hong Kong'},
                {"value": 'asia-south1', "title": 'Asia South 1 - Mumbai'},
                {"value": 'asia-northeast1', "title": 'Asia Northeast 1 - Tokyo'},
                {"value": 'asia-northeast3', "title": 'Asia Northeast 3 - Seoul'},
                {"value": 'asia-southeast1', "title": 'Asia Southeast 1 - Singapore'},
                {"value": 'asia-southeast2', "title": 'Asia Southeast 2 - Jakarta'},
                {"value": 'australia-southeast1', "title": 'Australia Southeast 1 - Sydney'},
                {"value": 'australia-southeast2', "title": 'Australia Southeast 2 - Melbourne'},
                {"value": 'me-west1', "title": 'Middle East West 1 - Dammam'},
                {"value": 'asia-northeast2', "title": 'Asia Northeast 2 - Osaka'},
                {"value": 'asia-northeast3', "title": 'Asia Northeast 3 - Seoul'},
                {"value": 'asia-south1', "title": 'Asia South 1 - Mumbai'},
                {"value": 'asia-southeast1', "title": 'Asia Southeast 1 - Singapore'},
                {"value": 'asia-southeast2', "title": 'Asia Southeast 2 - Jakarta'}
            ].sort((a, b) => a.title.localeCompare(b.title))
        }
    },
    inject: ['getWebsocket', 'registerMessageHandler', 'setWaitingForInput', 'requestSceneAssets', 'requestAppConfig'],

    methods: {
        show(tab, page) {
            this.requestAppConfig();
            this.dialog = true;
            if(tab) {
                this.tab = tab;
                if(page) {
                    this[tab + 'PageSelected'] = page;
                }
            }
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

            // check if presets component is present
            if(this.$refs.presets) {
                // update app_config.presets from $refs.presets.config

                let inferenceConfig = this.$refs.presets.inference_config();
                let embeddingsConfig = this.$refs.presets.embeddings_config();

                if(inferenceConfig) {
                    this.app_config.presets.inference = inferenceConfig;
                }

                if(embeddingsConfig) {
                    this.app_config.presets.embeddings = embeddingsConfig;
                }
            }

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
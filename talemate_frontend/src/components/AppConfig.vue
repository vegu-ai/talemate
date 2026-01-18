<template>
    <v-dialog v-model="dialog" scrollable max-width="960">
        <v-card v-if="app_config !== null">
            <v-card-title><v-icon class="mr-1">mdi-cog</v-icon>Settings</v-card-title>
            <v-tabs color="primary" v-model="tab">
                <v-tab value="game">
                    <v-icon start>mdi-gamepad-square</v-icon>
                    Game
                </v-tab>
                <v-tab value="appearance">
                    <v-icon start>mdi-palette-outline</v-icon>
                    Appearance
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
            <v-window v-model="tab" class="app-config-window">

                <!-- GAME -->

                <v-window-item value="game">
                    <div class="app-config-window-content">
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
                                                <v-checkbox color="primary" v-model="app_config.game.general.auto_save" label="Auto save" messages="Automatically save after each game-loop"></v-checkbox>
                                            </v-col>
                                        </v-row>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-checkbox color="primary" v-model="app_config.game.general.auto_progress" label="Auto progress" messages="AI automatically progresses after player turn."></v-checkbox>
                                            </v-col>
                                        </v-row>
                                        <v-row>
                                            <v-col cols="6">
                                                <v-number-input v-model="app_config.game.general.max_backscroll" label="Max backscroll" messages="Maximum number of messages to keep in the scene backscroll"></v-number-input>
                                            </v-col>
                                        </v-row>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-checkbox color="primary" v-model="app_config.game.general.show_agent_activity_bar" label="Show agent activity bar" messages="Display active agent actions in a horizontal bar above scene controls"></v-checkbox>
                                            </v-col>
                                        </v-row>        
                                    </div>
                                    <div v-else-if="gamePageSelected === 'character'">
                                        <v-alert color="white" variant="text" icon="mdi-human-edit" density="compact">
                                            <v-alert-title>Default player character</v-alert-title>
                                            <div class="text-grey">
                                                This will be default player character that will be added to a scene if the scene does not come with a defined player character. Mostly relevant when you load character-cards that aren't in the talemate scene format.                 
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
                                        <v-row>
                                            <v-col cols="12">
                                                <v-checkbox color="primary" v-model="app_config.game.general.add_default_character" label="Add default character to blank talemate scenes" messages="When creating a new scene, add the default player character to the scene."></v-checkbox>
                                            </v-col>
                                        </v-row>
                                    </div>
                                </v-col>
                            </v-row>
                        </v-card-text>
                    </v-card>
                    </div>
                </v-window-item>

                <!-- APPEARANCE -->

                <v-window-item value="appearance">
                    <div class="app-config-window-content">
                    <AppConfigAppearance 
                    ref="appearance"
                    :immutableConfig="app_config" 
                    :sceneActive="sceneActive"
                    @appearance-preview="onAppearancePreview"
                    ></AppConfigAppearance>
                    </div>
                </v-window-item>

                <!-- APPLICATION -->

                <v-window-item value="application">
                    <div class="app-config-window-content">
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

                                    <!-- DEEPSEEK API -->
                                    <div v-if="applicationPageSelected === 'deepseek_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>DeepSeek</v-alert-title>
                                            <div class="text-grey">
                                                Configure your DeepSeek API key here. You can get one from <a href="https://platform.deepseek.com/" target="_blank">https://platform.deepseek.com/</a>
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.deepseek.api_key"
                                                    label="DeepSeek API Key"></v-text-field>
                                            </v-col>
                                        </v-row>
                                    </div>

                                    <!-- OPENROUTER API -->
                                    <div v-if="applicationPageSelected === 'openrouter_api'">
                                        <v-alert color="white" variant="text" icon="mdi-api" density="compact">
                                            <v-alert-title>OpenRouter</v-alert-title>
                                            <div class="text-grey">
                                                Configure your OpenRouter API key here. You can get one from <a href="https://openrouter.ai/settings/keys" target="_blank">https://openrouter.ai/settings/keys</a> 
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field type="password" v-model="app_config.openrouter.api_key"
                                                    label="OpenRouter API Key"></v-text-field>
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
                                            <v-alert-title>Google</v-alert-title>
                                            <div class="text-grey">
                                                <p class="mb-2"><strong>Option&nbsp;1 – API&nbsp;Key&nbsp;(recommended)</strong></p>
                                                <p class="mb-1">Create a Google API key at <a href="https://aistudio.google.com/apikey" target="_blank">aistudio.google.com/apikey</a> and paste it in the field below. This is the quickest way to start using Gemini models.</p>

                                                <v-divider class="my-4"></v-divider>

                                                <p class="mb-2"><strong>Option&nbsp;2 – Vertex&nbsp;AI service&nbsp;account&nbsp;(advanced)</strong></p>
                                                <p class="mb-0">If you prefer using a full Google Cloud project, follow the setup guide <a href="https://cloud.google.com/vertex-ai/docs/start/client-libraries" target="_blank">here</a> to generate a service-account JSON credential file, then complete the legacy fields below.</p>

                                                <p class="text-caption mt-1 text-muted">
                                                    If both are setup, the API key will be used.
                                                </p>
                                            </div>
                                        </v-alert>
                                        <v-divider class="mb-2"></v-divider>
                                        <!-- API KEY -->
                                        <v-row class="mb-4">
                                            <v-col cols="12">
                                                <v-text-field type="password"
                                                              v-model="app_config.google.api_key"
                                                              label="Google API Key"
                                                              messages="Paste your Google API key here. This is the easiest way to authenticate.">
                                                </v-text-field>
                                            </v-col>
                                        </v-row>
                                        <!-- Vertex AI (legacy) fields -->
                                        <v-row>
                                            <v-col cols="12">
                                                <v-text-field v-model="app_config.google.gcloud_credentials_path"
                                                    label="Google Cloud Credentials Path" messages="Path to the service-account JSON credentials file on the machine running the Talemate backend."></v-text-field>
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


                                </v-col>
                            </v-row>
                        </v-card-text>
                    </v-card>
                    </div>
                </v-window-item>

                <!-- PRESETS -->

                <v-window-item value="presets">
                    <div class="app-config-window-content">
                    <AppConfigPresets 
                    ref="presets"
                    :immutable-config="app_config" 
                    :agentStatus="agentStatus"
                    :sceneActive="sceneActive"
                    :clientStatus="clientStatus"
                    ></AppConfigPresets>
                    </div>
                </v-window-item>

                <!-- CREATOR -->

                <v-window-item value="creator">
                    <div class="app-config-window-content">
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
                    </div>
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
import AppConfigAppearance from './AppConfigAppearance.vue';

export default {
    name: 'AppConfig',
    components: {
        AppConfigPresets,
        AppConfigAppearance,
    },
    props: {
        agentStatus: Object,
        sceneActive: Boolean,
        clientStatus: Object,
    },
    emits: [
        'appearance-preview',
        'appearance-preview-clear',
    ],
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
                appearance: [
                    {title: 'Scene', icon: 'mdi-script-text', value: 'scene'},
                ],
                application: [
                    {title: 'Anthropic', icon: 'mdi-api', value: 'anthropic_api'},
                    {title: 'Cohere', icon: 'mdi-api', value: 'cohere_api'},
                    {title: 'DeepSeek', icon: 'mdi-api', value: 'deepseek_api'},
                    {title: 'ElevenLabs', icon: 'mdi-api', value: 'elevenlabs_api'},
                    {title: 'Google', icon: 'mdi-api', value: 'google_api'},
                    {title: 'groq', icon: 'mdi-api', value: 'groq_api'},
                    {title: 'mistral.ai', icon: 'mdi-api', value: 'mistralai_api'},
                    {title: 'OpenAI', icon: 'mdi-api', value: 'openai_api'},
                    {title: 'OpenRouter', icon: 'mdi-api', value: 'openrouter_api'},
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

    watch: {
        dialog(newVal, oldVal) {
            // Clear preview whenever the dialog actually closes (including overlay/ESC close)
            if (oldVal === true && newVal === false) {
                this.$emit('appearance-preview-clear');
            }
        },
    },

    methods: {
        show(tab, page, item) {
            this.requestAppConfig();
            this.dialog = true;
            if(tab) {
                this.tab = tab;
                if(page) {
                    if(this[tab + 'PageSelected'] !== undefined) {
                        this[tab + 'PageSelected'] = page;
                    } else {
                        this.$nextTick(() => {
                            console.log("SETTING SELECTION", {tab, page, item});

                            if(this.$refs[tab] && this.$refs[tab].setSelection) {
                                this.$refs[tab].setSelection(page);
                            
                                this.$nextTick(() => {
                                    if(item && this.$refs[tab].$refs[page] && this.$refs[tab].$refs[page].setSelection) {
                                        this.$refs[tab].$refs[page].setSelection(item);
                                    }
                                });
                            }

                            
                        })
                    }
                }
            }
        },
        exit() {
            this.dialog = false;
        },
        onAppearancePreview(previewConfig) {
            // Re-emit appearance preview upward
            this.$emit('appearance-preview', previewConfig);
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
                    // exit() will emit appearance-preview-clear, no need to duplicate
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
                let inferenceGroupsConfig = this.$refs.presets.inference_groups_config();
                let embeddingsConfig = this.$refs.presets.embeddings_config();
                let systemPromptsConfig = this.$refs.presets.system_prompts_config();

                if(inferenceConfig) {
                    this.app_config.presets.inference = inferenceConfig;
                }

                if(inferenceGroupsConfig) {
                    this.app_config.presets.inference_groups = inferenceGroupsConfig;
                }

                if(embeddingsConfig) {
                    this.app_config.presets.embeddings = embeddingsConfig;
                }

                if(systemPromptsConfig) {
                    this.app_config.system_prompts = systemPromptsConfig;
                }

            }

            // check if appearance component is present
            if(this.$refs.appearance) {
                // update app_config.appearance from $refs.appearance.config
                this.app_config.appearance = this.$refs.appearance.get_config();
            }

            console.log("SAVING", this.app_config);

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
.app-config-window-content {
    overflow-y: auto;
    overflow-x: hidden;
    min-height: 0;
    max-height: calc(100vh - 250px);
}

/* Style scrollbar when it appears */
.app-config-window-content::-webkit-scrollbar {
    width: 8px;
}

.app-config-window-content::-webkit-scrollbar-track {
    background: rgba(0, 0, 0, 0.1);
}

.app-config-window-content::-webkit-scrollbar-thumb {
    background: rgba(0, 0, 0, 0.3);
    border-radius: 4px;
}

.app-config-window-content::-webkit-scrollbar-thumb:hover {
    background: rgba(0, 0, 0, 0.5);
}
</style>
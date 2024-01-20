<template>

    <v-sheet color="transparent" v-if="isEnvironment('scene')" class="mb-2">
        <v-spacer></v-spacer>
        <!-- quick settings as v-chips -->
        <v-chip size="x-small" v-for="(option, index) in quickSettings" :key="index" @click="toggleQuickSetting(option.value)"
            :color="option.status() === true ? 'success' : 'grey'"
            :disabled="isInputDisabled()" class="ma-1">
            <v-icon class="mr-1">{{ option.icon }}</v-icon>
            {{ option.title }}
            <v-icon class="ml-1" v-if="option.status() === true">mdi-check-circle-outline</v-icon>
            <v-icon class="ml-1" v-else-if="option.status() === false">mdi-circle-outline</v-icon>
            <v-tooltip v-else :text="option.status()">
                <template v-slot:activator="{ props }">
                    <v-icon class="ml-1" v-bind="props" color="orange">mdi-alert-outline</v-icon>
                </template>
            </v-tooltip>
        </v-chip>
    </v-sheet>

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
                        <v-btn class="hotkey" v-bind="props" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!rerun')" color="primary" icon>
                            <v-icon>mdi-refresh</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-tooltip v-if="isEnvironment('scene')" :disabled="isInputDisabled()" location="top"
                    text="Redo most recent AI message (Nuke Option - use this to attempt to break out of repetition)">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey" v-bind="props" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!rerun:0.5')" color="primary" icon>
                            <v-icon>mdi-nuke</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>


                <v-tooltip v-if="commandActive" location="top"
                    text="Abort / end action.">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mr-3" v-bind="props" :disabled="!isWaitingForInput()"
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

                <!-- actor actions -->

                <v-menu>
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" :disabled="isInputDisabled()" color="primary" icon>
                            <v-icon>mdi-account-voice</v-icon>
                        </v-btn>
                    </template>
                    <v-list>
                        <v-list-subheader>Actor Actions</v-list-subheader>
                        <v-list-item density="compact" v-for="npc_name in npc_characters" :key="npc_name"
                            @click="sendHotButtonMessage('!ai_dialogue_directed:' + npc_name)" prepend-icon="mdi-bullhorn">
                            <v-list-item-title>Talk with Direction ({{ npc_name }})</v-list-item-title>
                            <v-list-item-subtitle>Generate dialogue ({{ npc_name }}) with prompt guide</v-list-item-subtitle>
                        </v-list-item>
                        <v-list-item density="compact" v-for="npc_name in npc_characters" :key="npc_name"
                            @click="sendHotButtonMessage('!ai_dialogue_selective:' + npc_name)" prepend-icon="mdi-comment-account-outline">
                            <v-list-item-title>Talk ({{ npc_name }})</v-list-item-title>
                            <v-list-item-subtitle>Generate dialogue ({{ npc_name }})</v-list-item-subtitle>
                        </v-list-item>
                        <v-list-item density="compact" v-for="(option, index) in actorActions" :key="index"
                            @click="sendHotButtonMessage('!' + option.value)" :prepend-icon="option.icon">
                            <v-list-item-title>{{ option.title }}</v-list-item-title>
                            <v-list-item-subtitle>{{ option.description }}</v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                </v-menu>

                <!-- narrator actions -->

                <v-menu>
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" :disabled="isInputDisabled()" color="primary" icon>
                            <v-icon>mdi-script-text</v-icon>
                        </v-btn>
                    </template>
                    <v-list>
                        <v-list-subheader>Narrator Actions</v-list-subheader>

                        <v-list-item density="compact" v-for="(option, index) in narratorActions" :key="index"
                            @click="sendHotButtonMessage('!' + option.value)" :prepend-icon="option.icon">
                            <v-list-item-title>{{ option.title }}</v-list-item-title>
                            <v-list-item-subtitle>{{ option.description }}</v-list-item-subtitle>
                        </v-list-item>
                        <v-list-item density="compact" v-for="npc_name in npc_characters" :key="npc_name"
                            @click="sendHotButtonMessage('!narrate_c:' + npc_name)" prepend-icon="mdi-eye">
                            <v-list-item-title>Look at {{ npc_name }}</v-list-item-title>
                            <v-list-item-subtitle>Look at a character</v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                </v-menu>

                <!-- advance time -->

                <v-menu>
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" :disabled="isInputDisabled()" color="primary" icon>
                            <v-icon>mdi-clock</v-icon>
                        </v-btn>
                    </template>
                    <v-list density="compact">
                        <v-list-subheader>Advance Time</v-list-subheader>
                        <v-list-item density="compact" v-for="(option, index) in advanceTimeOptions" :key="index"
                            @click="sendHotButtonMessage('!advance_time:' + option.value)">
                            <v-list-item-title density="compact" class="text-capitalize">{{ option.title }}</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </v-menu>

            </v-card-actions>
        </v-card>

        <!-- Section 2: Tools -->
        <v-card class="hotbuttons-section-2">
            <v-card-actions>


                <!-- world tools -->

                <v-menu max-width="500px">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" :disabled="isInputDisabled()" color="primary" icon>
                            <v-icon>mdi-earth</v-icon>
                        </v-btn>
                    </template>
                    <v-list>

                        <v-list-subheader>Automatic state updates</v-list-subheader>
                        <div v-if="!worldStateTemplateFavoriteExists()">
                            <v-alert dense variant="text" color="grey" icon="mdi-cube-scan">
                                <span>There are no favorite world state templates. You can add them in the <b>World State Manager</b>. Favorites will be shown here.
                                </span>
                            </v-alert>
                        </div>
                        <div v-else>

                            <!-- character templates -->

                            <div v-for="npc_name in npc_characters" :key="npc_name">
                                <v-list-item v-for="(template, index) in worldStateTemplateFavoritesForNPCs()" :key="index"
                                    @click="handleClickWorldStateTemplate(template, npc_name)"
                                    prepend-icon="mdi-account">
                                    <template v-slot:append>
                                        <v-icon v-if="getTrackedCharacterState(npc_name, template.query) !== null" color="success">mdi-check-circle-outline</v-icon>
                                    </template>
                                    <v-list-item-title>{{ template.name }} ({{ npc_name }})</v-list-item-title>
                                    <v-list-item-subtitle>{{ template.description }}</v-list-item-subtitle>
                                </v-list-item>
                            </div>

                            <!-- player templates -->

                            <v-list-item v-for="(template, index) in worldStateTemplateFavoritesForPlayer()" :key="'player' + index"
                                @click="handleClickWorldStateTemplate(template, getPlayerCharacterName())"
                                prepend-icon="mdi-account-tie">
                                <template v-slot:append>
                                    <v-icon v-if="getTrackedCharacterState(getPlayerCharacterName(), template.query) !== null" color="success">mdi-check-circle-outline</v-icon>
                                </template>
                                <v-list-item-title>{{ template.name }} ({{ getPlayerCharacterName() }})</v-list-item-title>
                                <v-list-item-subtitle>
                                    {{ template.description }}
                                </v-list-item-subtitle>
                            </v-list-item>

                            <!-- world entry templates -->

                            <v-list-item v-for="(template, index) in worldStateTemplateFavoritesForWorldEntry()" :key="'worldEntry' + index"
                                @click="handleClickWorldStateTemplate(template)"
                                prepend-icon="mdi-earth">
                                <template v-slot:append>
                                    <v-icon v-if="getTrackedWorldState(template.query) !== null" color="success">mdi-check-circle-outline</v-icon>
                                </template>
                                <v-list-item-title>{{ template.name }}</v-list-item-title>
                                <v-list-item-subtitle>{{ template.description }}</v-list-item-subtitle>
                            </v-list-item>

                        </div>

                        <v-list-subheader>World State Tools</v-list-subheader>
                        <!-- open world state manager -->
                        <v-list-item density="compact" prepend-icon="mdi-book-open-page-variant" @click="openWorldStateManager()">
                            <v-list-item-title>Open the world state manager</v-list-item-title>
                            <v-list-item-subtitle>Manage characters, context and automatic state updates</v-list-item-subtitle>
                        </v-list-item>
                        <!-- update world state -->
                        <v-list-item density="compact" prepend-icon="mdi-refresh" @click="updateWorlState()">
                            <v-list-item-title>Update the world state</v-list-item-title>
                            <v-list-item-subtitle>Refresh the current world state snapshot</v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                </v-menu>
                
                <!-- save menu -->

                <v-menu>
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" :disabled="isInputDisabled()" color="primary" icon>
                            <v-icon>mdi-content-save</v-icon>
                        </v-btn>
                    </template>
                    <v-list>
                        <v-list-subheader>Save</v-list-subheader>
                        <v-list-item v-for="(option, index) in saveMenu" :key="index"
                            @click="sendHotButtonMessage('!' + option.value)"
                            :prepend-icon="option.icon">
                            <v-list-item-title>{{ option.title }}</v-list-item-title>
                            <v-list-item-subtitle>{{ option.description }}</v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                </v-menu>

                <!-- creative / game mode toggle -->

                <v-tooltip v-if="isEnvironment('scene')" :disabled="isInputDisabled()" location="top" text="Switch to creative mode">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" :disabled="isInputDisabled()"
                            @click="sendHotButtonMessage('!setenv_creative')" color="primary" icon>
                            <v-icon>mdi-palette-outline</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-tooltip v-else-if="isEnvironment('creative')" :disabled="isInputDisabled()" location="top" text="Switch to game mode">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-3" v-bind="props" :disabled="isInputDisabled()"
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
            autoSave: true,
            autoProgress: true,
            canAutoSave: false,
            npc_characters: [],

            quickSettings: [
                {"value": "toggleAutoSave", "title": "Auto Save", "icon": "mdi-content-save", "description": "Automatically save after each game-loop", "status": () => { return this.canAutoSave ? this.autoSave : "Manually save scene for auto-save to be available"; }},
                {"value": "toggleAutoProgress", "title": "Auto Progress", "icon": "mdi-robot", "description": "AI automatically progresses after player turn.", "status": () => { return this.autoProgress }},
            ],

            saveMenu: [
                {"value": "save_as", "title": "Save As", "icon": "mdi-content-save-all", "description": "Save the current scene as a new scene"},
                {"value": "save", "title": "Save", "icon": "mdi-content-save", "description": "Save the current scene"},
            ],

            narratorActions: [
                {"value": "narrate_progress", "title": "Progress Story", "icon": "mdi-script-text-play", "description": "Progress the story"},
                {"value": "narrate_progress_directed", "title": "Progress Story with Direction", "icon": "mdi-script-text-play", "description": "Progress the story (Provide prompt)"},
                {"value": "narrate_dialogue", "title": "Narrate Dialogue", "icon": "mdi-waves", "description": "Describe visuals, smells and sounds based on the recent dialogue."},
                {"value": "narrate_q", "title": "Query", "icon": "mdi-crystal-ball", "description": "Ask the narrator a question, or instruct to tell something."},
                {"value": "narrate", "title": "Look at Scene", "icon": "mdi-table-headers-eye", "description": "Look at the current scene"},
            ],

            actorActions: [
                {"value": "ai_dialogue", "title": "Talk", "icon": "mdi-comment-text-outline", "description": "Generate dialogue"},
            ],

            advanceTimeOptions: [
                {"value" : "P10Y", "title": "10 years"},
                {"value" : "P5Y", "title": "5 years"},
                {"value" : "P3Y", "title": "3 years"},
                {"value" : "P2Y", "title": "2 years"},
                {"value" : "P1Y", "title": "1 year"},
                {"value" : "P6M", "title": "6 months"},
                {"value" : "P3M", "title": "3 months"},
                {"value" : "P1M", "title": "1 month"},
                {"value" : "P14D:2 Weeks later", "title": "2 weeks"},
                {"value" : "P7D:1 Week later", "title": "1 week"},
                {"value" : "P3D", "title": "3 days"},
                {"value" : "P2D", "title": "2 days"},
                {"value" : "P1D", "title": "1 day"},
                {"value" : "PT12H", "title": "12 hours"},
                {"value" : "PT8H", "title": "8 hours"},
                {"value" : "PT4H", "title": "4 hours"},
                {"value" : "PT2H", "title": "2 hours"},
                {"value" : "PT1H", "title": "1 hour"},
                {"value" : "PT30M", "title": "30 minutes"},
                {"value" : "PT15M", "title": "15 minutes"},
                {"value" : "PT5M", "title": "5 minutes"}
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
        'appConfig',
        'getTrackedCharacterState',
        'getTrackedWorldState',
        'getPlayerCharacterName',
        'formatWorldStateTemplateString',
    ],
    computed:{
    },
    emits: [
        'open-world-state-manager',
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

        toggleQuickSetting(setting) {
            if (setting == "toggleAutoSave") {
                this.autoSave = !this.autoSave;
                this.getWebsocket().send(JSON.stringify({ type: 'quick_settings', action: 'set', setting: 'auto_save', value: this.autoSave }));
            } else if (setting == "toggleAutoProgress") {
                this.autoProgress = !this.autoProgress;
                this.getWebsocket().send(JSON.stringify({ type: 'quick_settings', action: 'set', setting: 'auto_progress', value: this.autoProgress }));
            }
        },

        handleClickWorldStateTemplate(template, character_name) {

            let query = this.formatWorldStateTemplateString(template.query, character_name);

            // if state is active, clicking should open the world state manager
            // otherwise, clicking should apply the template

            if(character_name) {
                let stateActive = this.getTrackedCharacterState(character_name, query) !== null;
                if (stateActive) {
                    this.openWorldStateManager("characters", character_name, "reinforce", query);
                } else {
                    this.sendHotButtonMessage('!apply_world_state_template:' + template.name + ':state_reinforcement:' + character_name);
                }
            } else {
                let stateActive = this.getTrackedWorldState(query) !== null;
                if (stateActive) {
                    this.openWorldStateManager("world", "states", query);
                } else {
                    this.sendHotButtonMessage('!apply_world_state_template:' + template.name + ':state_reinforcement');
                }
            }

        },

        worldStateTemplates: function() {
            let _templates = this.appConfig().game.world_state.templates.state_reinforcement;
            let templates = [];

            for (let key in _templates) {
                let template = _templates[key];
                templates.push(template);
            }
            return templates;
        },

        worldStateTemplateFavoriteExists: function() {
            for (let template of this.worldStateTemplates()) {
                if(template.favorite) {
                    return true;
                }
            }
            return false;
        },

        worldStateTemplateFavoritesForWorldEntry() {

            // 'world' entries

            let favorites = [];
            for (let template of this.worldStateTemplates()) {
                if(template.favorite && template.state_type == "world") {
                    favorites.push(template);
                }
            }
            return favorites;

        },

        worldStateTemplateFavoritesForNPCs() {

            // npc templates

            let favorites = [];
            for (let template of this.worldStateTemplates()) {
                if(template.favorite && (template.state_type == "npc" || template.state_type == "character")) {
                    favorites.push(template);
                }
            }
            return favorites;
        },

        worldStateTemplateFavoritesForPlayer() {

            // player templates

            let favorites = [];
            for (let template of this.worldStateTemplates()) {
                if(template.favorite && template.state_type == "player" || template.state_type == "character") {
                    favorites.push(template);
                }
            }
            return favorites;
        },

        openWorldStateManager(tab, sub1, sub2, sub3) {
            this.$emit('open-world-state-manager', tab, sub1, sub2, sub3);
        },

        updateWorlState() {
            this.getWebsocket().send(JSON.stringify({ type: 'interact', text: '!ws' }));
        },

        handleMessage(data) {

            if (data.type === "command_status") {
                if(data.status === "started") {
                    this.commandActive = true;
                    this.commandName = data.name;
                } else {
                    this.commandActive = false;
                    this.commandName = null;
                }
            } else if (data.type === "scene_status") {
                this.canAutoSave = data.data.can_auto_save;
                this.autoSave = data.data.auto_save;
                this.autoProgress = data.data.auto_progress;
                console.log({autoSave: this.autoSave, autoProgress: this.autoProgress});

                // collect npc characters
                this.npc_characters = [];
                for (let character of data.data.characters) {
                    if (!character.is_player) {
                        this.npc_characters.push(character.name);
                    }
                }
                return;
            } else if (data.type === "quick_settings" && data.action === 'set_done') {
                return;
            }


        },

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
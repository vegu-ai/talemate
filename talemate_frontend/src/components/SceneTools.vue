<template>

    <v-sheet color="transparent" class="mb-2">
        <v-spacer></v-spacer>
        <!-- quick settings as v-chips -->
        <v-chip size="x-small" v-for="(option, index) in quickSettings" :key="index" @click="toggleQuickSetting(option.value)"
            :color="option.status() === true ? 'success' : 'grey'"
            :disabled="appBusy" class="ma-1">
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

        <v-tooltip v-if="sceneHelp" :text="sceneHelp" class="pre-wrap">
            <template v-slot:activator="{ props }">
                <v-chip size="x-small" v-bind="props" color="primary" variant="text" class="ma-1">
                    <v-icon class="mr-1">mdi-help-circle-outline</v-icon>
                    {{ sceneName }} instructions
                </v-chip>
            </template>
        </v-tooltip>

        <v-tooltip v-if="sceneExperimental" text="This scenario is classified as experimental, likely requiring usage of a strong LLM to produce a decent experience." class="pre-wrap">
            <template v-slot:activator="{ props }">
                <v-chip size="x-small" v-bind="props" variant="text" color="warning" class="ma-1">
                    <v-icon class="mr-1">mdi-flask</v-icon>
                    Experimental
                </v-chip>
            </template>
        </v-tooltip>

        <!-- if in creative mode provide a button to exit -->
        <v-tooltip v-if="scene?.environment === 'creative'" text="Exit creative mode">
            <template v-slot:activator="{ props }">
                <v-chip size="x-small" v-bind="props" variant="tonal" color="secondary" class="ma-1" @click="exitCreativeMode()">
                    <v-icon class="mr-1">mdi-exit-to-app</v-icon>
                    Exit creative mode
                </v-chip>
            </template>
        </v-tooltip>
    </v-sheet>

    <!-- Hotbuttons Section -->
    <div class="hotbuttons-section">


        <!-- Section 0: Loading indicator and regenerate tool -->

        <v-card class="hotbuttons-section-1">
            <v-card-actions>
                <v-progress-circular class="ml-3 mr-3" size="24" v-if="appBusy" indeterminate="disable-shrink"
                    color="primary"></v-progress-circular>                
                <v-icon class="ml-3 mr-3" v-else-if="isWaitingForInput()">mdi-keyboard</v-icon>
                <v-icon class="ml-3 mr-3" v-else>mdi-circle-outline</v-icon>

                <v-tooltip v-if="appBusy" location="top"
                    text="Interrupt the current generation(s)"
                    class="pre-wrap"
                    max-width="300px">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mr-3" v-bind="props"
                            @click="interruptScene" color="primary" icon>
                            <v-icon>mdi-stop-circle-outline</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-divider vertical></v-divider>


                <v-tooltip :disabled="appBusy" location="top"
                    :text="'Redo most recent AI message.\n[Ctrl: Provide instructions, +Alt: Rewrite]'"
                    class="pre-wrap"
                    max-width="300px">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey" v-bind="props" :disabled="appBusy"
                            @click="regenerate" color="primary" icon>
                            <v-icon>mdi-refresh</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-tooltip :disabled="appBusy" location="top"
                    :text="'Redo most recent AI message (Nuke Option - use this to attempt to break out of repetition) \n[Ctrl: Provide instructions, +Alt: Rewrite]'"
                    class="pre-wrap"
                    max-width="300px">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey" v-bind="props" :disabled="appBusy"
                            @click="regenerateNuke" color="primary" icon>
                            <v-icon>mdi-nuke</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>


                <v-tooltip v-if="commandActive" location="top"
                    text="Abort / end action.">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mr-1" v-bind="props" :disabled="!isWaitingForInput()"
                            @click="sendHotButtonMessage('!abort')" color="primary" icon>
                            <v-icon>mdi-cancel</v-icon>
                            
                        </v-btn>
                        <span class="mr-1 ml-3 text-caption text-muted">{{ commandName }}</span>
                    </template>
                </v-tooltip>
            </v-card-actions>
        </v-card>


        <!-- Section 2: Game Actions & Tools -->
        <v-card class="hotbuttons-section-2">
            <v-card-text class="pa-2">
                <div class="d-flex flex-wrap align-center" style="gap: 4px;">

                <!-- actor actions -->

                <SceneToolsActor :disabled="appBusy" :npc-characters="npc_characters" />

                <!-- narrator actions -->

                <SceneToolsNarrator :disabled="appBusy" ref="narratorTools" :npc-characters="npc_characters" />

                <!-- director actions -->

                <SceneToolsDirector :disabled="appBusy" ref="directorTools" :npc-characters="npc_characters" />

                <!-- advance time -->

                <v-menu>
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-1" v-bind="props" :disabled="appBusy" color="primary" icon variant="text">
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

                <!-- world tools -->

                <v-menu max-width="500px">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-1" v-bind="props" :disabled="appBusy" color="primary" icon variant="text">
                            <v-icon>mdi-earth</v-icon>
                        </v-btn>
                    </template>
                    <v-list>

                        <v-list-subheader>Automatic state updates</v-list-subheader>
                        <div v-if="!worldStateReinforcementFavoriteExists()">
                            <v-alert dense variant="text" color="grey" icon="mdi-cube-scan">
                                <span>There are no favorite world state templates. You can add them in the <b>World State Manager</b>. Favorites will be shown here.
                                </span>
                            </v-alert>
                        </div>
                        <div v-else>

                            <!-- character templates -->

                            <div v-for="npc_name in npc_characters" :key="npc_name">
                                <v-list-item v-for="(template, index) in worldStateReinforcementFavoritesForNPCs()" :key="index"
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

                            <v-list-item v-for="(template, index) in worldStateReinforcementFavoritesForPlayer()" :key="'player' + index"
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

                            <v-list-item v-for="(template, index) in worldStateReinforcementFavoritesForWorldEntry()" :key="'worldEntry' + index"
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
                

                <!-- creative tools -->
                
                <SceneToolsCreative 
                    :disabled="appBusy"
                    :active-characters="activeCharacters"
                    :inactive-characters="inactiveCharacters"
                    :passive-characters="passiveCharacters"
                    :player-character-name="playerCharacterName"
                    :scene="scene"
                    :world-state-templates="worldStateTemplates"
                />
                <!-- visualizer actions -->
             
                <SceneToolsVisual 
                    :disabled="appBusy"
                    :agent-status="agentStatus"
                    :visual-agent-ready="visualAgentReady"
                    :npc-characters="npc_characters"
                />

                <!-- save menu -->

                <SceneToolsSave :app-busy="appBusy" />


                </div>
            </v-card-text>
        </v-card>



    </div>
</template>


<script>
import SceneToolsDirector from './SceneToolsDirector.vue';
import SceneToolsNarrator from './SceneToolsNarrator.vue';
import SceneToolsActor from './SceneToolsActor.vue';
import SceneToolsCreative from './SceneToolsCreative.vue';
import SceneToolsVisual from './SceneToolsVisual.vue';
import SceneToolsSave from './SceneToolsSave.vue';
export default {

    name: 'SceneTools',
    components: {
        SceneToolsDirector,
        SceneToolsNarrator,
        SceneToolsActor,
        SceneToolsCreative,
        SceneToolsVisual,
        SceneToolsSave,
    },
    props: {
        appBusy: Boolean,
        passiveCharacters: Array,
        inactiveCharacters: Array,
        activeCharacters: Array,
        playerCharacterName: String,
        messageInput: String,
        worldStateTemplates: Object,
        agentStatus: Object,
        scene: Object,
    },
    computed: {
        deactivatableCharacters() {
            // this.activeCharacters without playerCharacterName
            let characters = [];
            for (let character of this.activeCharacters) {
                if (character !== this.playerCharacterName) {
                    characters.push(character);
                }
            }
            return characters;
        },
        worldStateReinforcementTemplates() {
            let _templates = this.worldStateTemplates.by_type.state_reinforcement;
            let templates = [];

            for (let key in _templates) {
                let template = _templates[key];
                templates.push(template);
            }
            return templates;
        },
        creativeGameMenuFiltered() {
            return this.creativeGameMenu.filter(option => {
                if (option.condition) {
                    return option.condition();
                } else {
                    return true;
                }
            });
        }
    },
    data() {
        return {
            commandActive: false,
            commandName: null,
            autoSave: true,
            autoProgress: true,
            sceneName: "Scene",
            sceneHelp: "",
            sceneExperimental: false,
            canAutoSave: false,
            visualAgentReady: false,
            npc_characters: [],

            quickSettings: [
                {"value": "toggleAutoSave", "title": "Auto Save", "icon": "mdi-content-save", "description": "Automatically save after each game-loop", "status": () => { return this.canAutoSave ? this.autoSave : "Manually save scene for auto-save to be available"; }},
                {"value": "toggleAutoProgress", "title": "Auto Progress", "icon": "mdi-robot", "description": "AI automatically progresses after player turn.", "status": () => { return this.autoProgress }},
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
        'setInputDisabled',
        'isWaitingForInput',
        'creativeEditor',
        'appConfig',
        'getTrackedCharacterState',
        'getTrackedWorldState',
        'getPlayerCharacterName',
        'formatWorldStateTemplateString',
        'characterSheet',
    ],
    emits: [
        'open-world-state-manager',
    ],
    methods: {

        sendHotButtonMessage(message) {
            if (message == "!abort" || !this.appBusy) {
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
                    this.getWebsocket().send(JSON.stringify({
                        type: "world_state_manager",
                        action: "apply_template",
                        template: template,
                        character_name: character_name,
                        run_immediately: true,
                    }));
                }
            } else {
                let stateActive = this.getTrackedWorldState(query) !== null;
                if (stateActive) {
                    this.openWorldStateManager("world", "states", query);
                } else {
                    this.getWebsocket().send(JSON.stringify({
                        type: "world_state_manager",
                        action: "apply_template",
                        template: template,
                        character_name: null,
                        run_immediately: true,
                    }));
                }
            }

        },

        worldStateReinforcementFavoriteExists: function() {
            for (let template of this.worldStateReinforcementTemplates) {
                if(template.favorite) {
                    return true;
                }
            }
            return false;
        },

        worldStateReinforcementFavoritesForWorldEntry() {

            // 'world' entries

            let favorites = [];
            for (let template of this.worldStateReinforcementTemplates) {
                if(template.favorite && template.state_type == "world") {
                    favorites.push(template);
                }
            }
            return favorites;

        },

        worldStateReinforcementFavoritesForNPCs() {

            // npc templates

            let favorites = [];
            for (let template of this.worldStateReinforcementTemplates) {
                if(template.favorite && (template.state_type == "npc" || template.state_type == "character")) {
                    favorites.push(template);
                }
            }
            return favorites;
        },

        worldStateReinforcementFavoritesForPlayer() {

            // player templates

            let favorites = [];
            for (let template of this.worldStateReinforcementTemplates) {
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

        regenerate(event) {
            // if ctrl is pressed use directed regenerate
            let withDirection = event.ctrlKey;
            let method = event.altKey || event.metaKey ? "edit" : "replace";
            let command = "!regenerate";

            if(withDirection)
                command += "_directed";

            command += ":0.0:"+method;

            // if alt is pressed 

            this.sendHotButtonMessage(command)
        },

        regenerateNuke(event) {
            // if ctrl is pressed use directed regenerate
            let withDirection = event.ctrlKey;
            let method = event.altKey || event.metaKey ? "edit" : "replace";
            let command = "!regenerate";

            if(withDirection)
                command += "_directed";

            // 0.5 nuke adjustment
            command += ":0.5:"+method;

            this.sendHotButtonMessage(command)
        },

        requestAutocompleteSuggestion() {
            this.getWebsocket().send(JSON.stringify({ type: 'interact', text: `!acdlg:${this.messageInput}` }));
        },


        interruptScene() {
            this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
        },

        exitCreativeMode() {
            this.sendHotButtonMessage('!setenv_scene');
        },

        // Handle incoming messages

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
                this.sceneHelp = data.data.help;
                this.sceneExperimental = data.data.experimental;
                this.sceneName = data.name;

                // collect npc characters
                this.npc_characters = [];
                for (let character of data.data.characters) {
                    if (!character.is_player) {
                        this.npc_characters.push(character.name);
                    }
                }
                return;
            } else if (data.type === 'agent_status' && data.name === 'visual') {
                this.visualAgentReady = data.status == 'idle' || data.status == 'busy' || data.status == 'busy_bg';
            } else if (data.type === "quick_settings" && data.action === 'set_done') {
                return;
            }


        },

    },
    mounted() {
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
    flex-wrap: wrap;
    gap: 5px;
}

.hotbuttons-section-1,
.hotbuttons-section-2,
.hotbuttons-section-3 {
    display: flex;
    align-items: center;
    flex-shrink: 0;
    min-width: 0;
}

/* Make card content responsive */
.hotbuttons-section-2 .v-card-text {
    padding: 8px !important;
}

.hotbuttons-section-2 .d-flex {
    min-height: 40px;
}

/* Consistent button styling for all sections */
.hotbuttons-section .v-btn,
.hotbuttons-section-1 .v-btn,
.hotbuttons-section-2 .v-btn {
    min-width: 40px !important;
    width: 40px !important;
    height: 40px !important;
    padding: 0 !important;
    margin: 2px !important;
}

.hotbuttons-section .v-btn.v-btn--icon,
.hotbuttons-section-1 .v-btn.v-btn--icon,
.hotbuttons-section-2 .v-btn.v-btn--icon {
    border-radius: 50% !important;
}

.hotbuttons-section .v-progress-circular,
.hotbuttons-section-1 .v-progress-circular,
.hotbuttons-section-2 .v-progress-circular {
    margin: 2px 4px;
}

/* Ensure proper spacing for child components */
.hotbuttons-section-2 > div > * {
    margin: 2px;
}

/* Ensure v-card-actions maintains compact styling */
.hotbuttons-section-1 .v-card-actions {
    padding: 8px !important;
    min-height: 40px;
}

@media (max-width: 768px) {
    .hotbuttons-section {
        flex-direction: column;
        align-items: stretch;
    }
    
    .hotbuttons-section-1,
    .hotbuttons-section-2,
    .hotbuttons-section-3 {
        width: 100%;
        margin-bottom: 5px;
    }
    
    .hotbuttons-section-2 .d-flex {
        justify-content: center;
    }
}

@media (max-width: 480px) {
    .hotbuttons-section {
        gap: 3px;
    }
    
    .hotbuttons-section-2 .d-flex {
        gap: 2px !important;
    }
    
    .hotbuttons-section .v-btn,
    .hotbuttons-section-1 .v-btn,
    .hotbuttons-section-2 .v-btn {
        min-width: 36px !important;
        width: 36px !important;
        height: 36px !important;
        margin: 1px !important;
    }
}

.pre-wrap {
    white-space: pre-wrap;
}

.btn-notification {
    position: absolute;
    top: 0px;
    right: 0px;
    font-size: 15px;
    border-radius: 50%;
    width: 20px;
    height: 20px;
    display: flex;
    justify-content: center;
    align-items: center;
}

.hotbuttons-section .v-btn.v-btn--variant-elevated,
.hotbuttons-section-1 .v-btn.v-btn--variant-elevated,
.hotbuttons-section-2 .v-btn.v-btn--variant-elevated {
    background-color: transparent !important;
    box-shadow: none !important;
}
</style>
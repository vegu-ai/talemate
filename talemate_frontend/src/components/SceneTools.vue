<template>

    <v-sheet color="transparent" class="mb-2">
        <v-spacer></v-spacer>
        <!-- quick settings as v-chips -->
        <v-chip size="x-small" v-for="(option, index) in quickSettings" :key="index" @click="toggleQuickSetting(option.value)"
            :color="option.status() === true ? 'success' : 'grey'"
            :disabled="appBusy || !appReady" class="ma-1">
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

        <SceneToolsSettings :app-busy="appBusy" :app-ready="appReady" />

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
        <v-chip v-if="scene?.environment === 'creative'" size="x-small" variant="tonal" color="secondary" class="ma-1" @click="exitCreativeMode()">
            <v-icon class="mr-1">mdi-exit-to-app</v-icon>
            Exit node editor
        </v-chip>

        <v-chip
            class="mx-1 text-capitalize agent-message-chip"
            :class="{ 'highlight-flash': messageHighlights[agent_name] }"
            @click="openAgentMessages(agent_name)"
            v-for="(message, agent_name) in agentMessages"
            :key="agent_name"
            color="highlight2"
            size="x-small">
            <v-icon class="mr-1">mdi-message-text-outline</v-icon>
            {{ agent_name }} {{ message.data.action }}
        </v-chip>
    </v-sheet>

    <RequestInput
        ref="requestDirectedRegenerate"
        title="Directed regenerate"
        instructions="Provide instructions for regeneration. Ctrl+Enter submits."
        icon="mdi-refresh"
        inputType="multiline"
        @continue="directedRegenerateContinue"
        @cancel="pendingDirectedRegen = null"
    />

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

                <!-- audio control -->
                <v-tooltip v-if="ttsAgentEnabled" location="top" text="Stop audio">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mr-3" v-bind="props"
                            @click="cancelAudioQueue" 
                            :color="audioPlayedForMessageId ? 'play_audio' : 'default'"
                            :disabled="!audioPlayedForMessageId" 
                            icon>
                            <v-icon>mdi-volume-high</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-tooltip :disabled="appBusy || !appReady" location="top"
                    :text="'Redo most recent AI message.\n[Ctrl: Provide instructions, +Alt: Rewrite]'"
                    class="pre-wrap"
                    max-width="300px">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey" v-bind="props" :disabled="appBusy || !appReady"
                            @click="regenerate" color="primary" icon>
                            <v-icon>mdi-refresh</v-icon>
                        </v-btn>
                    </template>
                </v-tooltip>

                <v-tooltip :disabled="appBusy || !appReady" location="top"
                    :text="'Redo most recent AI message (Nuke Option - use this to attempt to break out of repetition) \n[Ctrl: Provide instructions, +Alt: Rewrite]'"
                    class="pre-wrap"
                    max-width="300px">
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey" v-bind="props" :disabled="appBusy || !appReady"
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

                <SceneToolsActor :disabled="appBusy || !appReady" :npc-characters="npc_characters" />

                <!-- narrator actions -->

                <SceneToolsNarrator :disabled="appBusy || !appReady" ref="narratorTools" :npc-characters="npc_characters" />

                <!-- director actions -->

                <SceneToolsDirector :disabled="appBusy || !appReady" ref="directorTools" :npc-characters="npc_characters" />

                <!-- advance time -->

                <v-menu>
                    <template v-slot:activator="{ props }">
                        <v-btn class="hotkey mx-1" v-bind="props" :disabled="appBusy || !appReady" color="primary" icon variant="text">
                            <v-icon>mdi-clock</v-icon>
                        </v-btn>
                    </template>
                    <v-list density="compact">
                        <v-list-subheader>Advance Time</v-list-subheader>
                        <v-list-item density="compact" v-for="(option, index) in advanceTimeOptions" :key="index"
                            @click="advanceTime(option.value)">
                            <v-list-item-title density="compact" class="text-capitalize">{{ option.title }}</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </v-menu>

                <!-- world tools -->
                <SceneToolsWorld 
                    :disabled="appBusy || !appReady"
                    :npc-characters="npc_characters"
                    :world-state-templates="worldStateTemplates"
                    @open-world-state-manager="openWorldStateManager"
                />
                

                <!-- creative tools -->
                
                <SceneToolsCreative 
                    :disabled="appBusy || !appReady"
                    :active-characters="activeCharacters"
                    :inactive-characters="inactiveCharacters"
                    :passive-characters="passiveCharacters"
                    :player-character-name="playerCharacterName"
                    :scene="scene"
                    :world-state-templates="worldStateTemplates"
                />
                <!-- visualizer actions -->
             
                <SceneToolsVisual 
                    :disabled="appBusy || !appReady"
                    :agent-status="agentStatus"
                    :visual-agent-ready="visualAgentReady"
                    :npc-characters="npc_characters"
                    :player-character="playerCharacterName"
                />

                <!-- save menu -->

                <SceneToolsSave :app-busy="appBusy" :app-ready="appReady" :scene="scene" />


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
import SceneToolsWorld from './SceneToolsWorld.vue';
import SceneToolsSettings from './SceneToolsSettings.vue';
import SceneToolsSave from './SceneToolsSave.vue';
import RequestInput from './RequestInput.vue';
export default {

    name: 'SceneTools',
    components: {
        SceneToolsDirector,
        SceneToolsNarrator,
        SceneToolsActor,
        SceneToolsCreative,
        SceneToolsVisual,
        SceneToolsSave,
        SceneToolsWorld,
        SceneToolsSettings,
        RequestInput,
    },
    props: {
        appBusy: Boolean,
        appReady: {
            type: Boolean,
            default: true,
        },
        passiveCharacters: Array,
        inactiveCharacters: Array,
        activeCharacters: Array,
        playerCharacterName: String,
        messageInput: String,
        worldStateTemplates: Object,
        agentStatus: Object,
        scene: Object,
        visualAgentReady: Boolean,
        audioPlayedForMessageId: [Number, String],
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
        
        creativeGameMenuFiltered() {
            return this.creativeGameMenu.filter(option => {
                if (option.condition) {
                    return option.condition();
                } else {
                    return true;
                }
            });
        },

        ttsAgentEnabled() {
            const ttsAgent = this.agentStatus?.tts;
            return ttsAgent && ttsAgent.available;
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
            npc_characters: [],
            agentMessages: {},
            messageHighlights: {},
            pendingDirectedRegen: null,
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
        'openAppConfig',
    ],
    emits: [
        'open-world-state-manager',
        'open-agent-messages',
        'cancel-audio-queue',
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

        openWorldStateManager(tab, sub1, sub2, sub3) {
            this.$emit('open-world-state-manager', tab, sub1, sub2, sub3);
        },

        openAgentMessages(agent_name) {
            delete this.agentMessages[agent_name];
            this.$emit('open-agent-messages', agent_name);
        },

        directedRegenerateContinue(direction) {
            if (!this.pendingDirectedRegen) return;
            if (this.appBusy) return;

            const { nuke_repetition, method } = this.pendingDirectedRegen;
            this.pendingDirectedRegen = null;

            this.setInputDisabled(true);
            this.getWebsocket().send(JSON.stringify({
                type: 'assistant',
                action: 'regenerate_directed',
                nuke_repetition,
                method,
                direction,
            }));
        },

        regenerate(event) {
            // if ctrl is pressed use directed regenerate
            let withDirection = event.ctrlKey;
            let method = event.altKey || event.metaKey ? "edit" : "replace";
            const nuke_repetition = 0.0;

            if (withDirection) {
                this.pendingDirectedRegen = { nuke_repetition, method };
                this.$refs.requestDirectedRegenerate?.openDialog({});
                return;
            }

            if (this.appBusy) return;

            this.setInputDisabled(true);
            this.getWebsocket().send(JSON.stringify({
                type: 'assistant',
                action: 'regenerate',
                nuke_repetition,
            }));
        },

        regenerateNuke(event) {
            // if ctrl is pressed use directed regenerate
            let withDirection = event.ctrlKey;
            let method = event.altKey || event.metaKey ? "edit" : "replace";
            const nuke_repetition = 0.5;

            if (withDirection) {
                this.pendingDirectedRegen = { nuke_repetition, method };
                this.$refs.requestDirectedRegenerate?.openDialog({});
                return;
            }

            if (this.appBusy) return;

            this.setInputDisabled(true);
            this.getWebsocket().send(JSON.stringify({
                type: 'assistant',
                action: 'regenerate',
                nuke_repetition,
            }));
        },


        interruptScene() {
            this.getWebsocket().send(JSON.stringify({ type: 'interrupt' }));
        },

        exitCreativeMode() {
            if (this.appBusy) return;
            this.setInputDisabled(true);
            this.getWebsocket().send(JSON.stringify({ type: 'assistant', action: 'set_environment', environment: 'scene' }));
        },

        cancelAudioQueue() {
            this.$emit('cancel-audio-queue');
        },

        advanceTime(duration) {
            this.getWebsocket().send(JSON.stringify({ type: 'world_state_agent', action: 'advance_time', duration: duration }));
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
            } else if (data.type === "quick_settings" && data.action === 'set_done') {
                return;
            } else if (data.type === "assistant" && data.action === "regenerate_done") {
                this.setInputDisabled(!this.isWaitingForInput());
                return;
            } else if (data.type === "assistant" && data.action === "regenerate_failed") {
                this.setInputDisabled(!this.isWaitingForInput());
                return;
            } else if (data.type === 'agent_message') {
                const agent = data.data.agent;
                this.agentMessages[agent] = data;

                // Trigger highlight animation
                this.messageHighlights[agent] = true;
                setTimeout(() => {
                    this.messageHighlights[agent] = false;
                }, 1000); // Remove highlight after 1 second
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

.agent-message-chip {
    transition: all 0.3s ease-in-out;
}

.agent-message-chip.highlight-flash {
    animation: highlight-pulse 1s ease-in-out;
}

@keyframes highlight-pulse {
    0% {
        transform: scale(1);
        box-shadow: 0 0 0 rgba(var(--v-theme-highlight2), 0.4);
    }
    50% {
        transform: scale(1.05);
        box-shadow: 0 0 10px rgba(var(--v-theme-highlight2), 0.8);
    }
    100% {
        transform: scale(1);
        box-shadow: 0 0 0 rgba(var(--v-theme-highlight2), 0.4);
    }
}

.hotbuttons-section .v-btn.v-btn--variant-elevated,
.hotbuttons-section-1 .v-btn.v-btn--variant-elevated,
.hotbuttons-section-2 .v-btn.v-btn--variant-elevated {
    background-color: transparent !important;
    box-shadow: none !important;
}
</style>
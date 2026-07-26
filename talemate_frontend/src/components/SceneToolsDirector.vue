<template>
    <v-menu location="top">
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon variant="text">
                <v-icon>mdi-bullhorn</v-icon>
            </v-btn>
        </template>
        <v-list>
            <v-list-subheader>Director Actions</v-list-subheader>
            <!-- Generate dynamic choices  -->
            <v-list-item
                density="compact"
                @click="actionRequestDynamicChoices"
                prepend-icon="mdi-tournament"
            >
                <v-list-item-title>Generate dynamic actions<v-chip variant="text" color="highlight5" class="ml-1" size="x-small">{{ primaryModifierLabel }}: Provide direction</v-chip></v-list-item-title>
                <v-list-item-subtitle>{{ getActAsCharacterName() }}</v-list-item-subtitle>
            </v-list-item>
            <!-- Trigger scene direction turn -->
            <v-list-item
                density="compact"
                @click="actionSceneDirectionTurn"
                prepend-icon="mdi-movie-play"
                :disabled="!sceneDirectionEnabled"
            >
                <v-list-item-title>Scene direction turn<v-chip variant="text" color="highlight5" class="ml-1" size="x-small">{{ primaryModifierLabel }}: Provide direction</v-chip></v-list-item-title>
                <v-list-item-subtitle>Manually trigger a scene direction turn</v-list-item-subtitle>
            </v-list-item>
            <!-- Generate long progress -->
            <v-list-item
                density="compact"
                @click="openScenePlanDialog"
                prepend-icon="mdi-movie-open"
            >
                <v-list-item-title>Generate long progress</v-list-item-title>
                <v-list-item-subtitle>Plan and generate a whole progress arc</v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>

    <!-- narrative direction input -->
    <RequestInput ref="instructionsInput" title="Director Prompt"
        :instructions="'Instructions - Provide an instruction for the director to follow for this action'"
        input-type="multiline" icon="mdi-dice-multiple" :size="750" @continue="applyDirection" />

    <!-- Scene plan dialog -->
    <v-dialog v-model="scenePlanDialog" max-width="800">
        <v-card>
            <v-card-title><v-icon class="mr-2">mdi-movie-open</v-icon>Generate Long Progress</v-card-title>
            <v-card-text>
                <div class="text-muted mb-4">Automatically plans and generates multiple turns of narrative progress based on your instructions. The director will create an outline and then execute each turn sequentially.</div>
                <v-textarea
                    v-model="scenePlanInstructions"
                    label="Scene instructions"
                    hint="Describe what should happen in the scene"
                    rows="8"
                    auto-grow
                ></v-textarea>

                <div class="d-flex ga-4 align-center mt-4">
                    <v-slider
                        v-model="scenePlanBeats"
                        label="Number of turns"
                        :min="3"
                        :max="24"
                        :step="1"
                        thumb-label="always"
                        color="primary"
                        class="flex-grow-1"
                    ></v-slider>
                    <v-slider
                        v-model="scenePlanDialogueRatio"
                        label="Dialogue ratio"
                        :min="0"
                        :max="100"
                        :step="10"
                        thumb-label="always"
                        color="primary"
                        class="flex-grow-1"
                    >
                        <template v-slot:thumb-label="{ modelValue }">{{ modelValue }}%</template>
                    </v-slider>
                </div>

                <div class="d-flex align-center ga-4 mb-2">
                    <v-btn-toggle
                        v-model="scenePlanMode"
                        mandatory
                        density="compact"
                        color="primary"
                    >
                        <v-btn value="generate_arc_expand" size="small" variant="text">
                            <v-icon start>mdi-lightning-bolt</v-icon>
                            Expand
                        </v-btn>
                        <v-btn value="generate_arc" size="small" variant="text">
                            <v-icon start>mdi-directions-fork</v-icon>
                            Turn by turn
                        </v-btn>
                    </v-btn-toggle>
                    <v-checkbox
                        v-model="scenePlanCloseArc"
                        label="Close the arc"
                        density="compact"
                        hide-details
                        color="primary"
                    ></v-checkbox>
                    <v-checkbox
                        v-model="scenePlanOutlineCritique"
                        label="Outline critique"
                        density="compact"
                        hide-details
                        color="primary"
                    ></v-checkbox>
                    <v-checkbox
                        v-model="scenePlanExpandCritique"
                        label="Expansion critique"
                        density="compact"
                        hide-details
                        color="primary"
                        v-if="scenePlanMode === 'generate_arc_expand'"
                    ></v-checkbox>
                </div>
                <div class="text-caption text-muted mb-1" v-if="scenePlanMode === 'generate_arc'">Each beat is executed individually through narrator and conversation agents. Slower, but the director can adjust strategy between beats.</div>
                <div class="text-caption text-muted mb-1" v-else>Beats are expanded into prose in chunks. Much faster, with automatic chunking and arc-aware pacing.</div>
                <div class="text-caption text-muted mb-4">
                    <v-icon size="x-small" class="mr-1">mdi-information-outline</v-icon>
                    <span v-if="scenePlanCloseArc">Closed arc: lands a full resolution. Use when writing a self-contained short story.</span>
                    <span v-else>Continuation: ends on a handoff moment so you can keep playing from where the arc leaves off.</span>
                </div>

                <!-- Warnings - compact format -->
                <div v-if="narratorProgressStoryLength < minRecommendedNarratorLength" class="text-caption text-warning mb-1">
                    <v-icon size="x-small" color="warning" class="mr-1">mdi-alert</v-icon>
                    Narrator Progress Story length ({{ narratorProgressStoryLength }} tokens) is below recommended {{ minRecommendedNarratorLength }}.
                    <v-btn size="x-small" variant="text" color="warning" @click="openAgentSettings('narrator', 'generation_override')">Fix</v-btn>
                </div>
                <div v-if="charactersMissingActingInstructions.length > 0" class="text-caption text-warning mb-1">
                    <v-icon size="x-small" color="warning" class="mr-1">mdi-alert</v-icon>
                    Missing acting instructions: <strong>{{ charactersMissingActingInstructions.join(', ') }}</strong>
                </div>
                <div class="text-caption text-muted mb-1">
                    <v-icon size="x-small" class="mr-1">mdi-information-outline</v-icon>
                    May generate actions and dialogue for player controlled characters. Requires a strong LLM (100B+ parameters).
                </div>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="cancel" prepend-icon="mdi-close" @click="scenePlanDialog = false">Cancel</v-btn>
                <v-btn color="primary" prepend-icon="mdi-play" @click="actionCreateScenePlan" :disabled="!scenePlanInstructions.trim()">Plan &amp; Generate</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

</template>

<script>
import RequestInput from './RequestInput.vue';
import { effectiveActionEnabled } from '@/constants/sceneAgentSettings';
import { isPrimaryModifier, primaryModifierLabel } from '@/utils/keyboardModifiers';

export default {
    name: "SceneToolsDirector",
    components: {
        RequestInput,
    },
    props: {
        npcCharacters: Array,
        sceneCharacters: Array,
        disabled: Boolean,
        agentStatus: Object,
    },
    inject: ['getWebsocket', 'getActAsCharacterName', 'openDirectorConsole', 'openAgentSettings'],
    data() {
        return {
            primaryModifierLabel,
            scenePlanDialog: false,
            scenePlanInstructions: '',
            scenePlanBeats: 8,
            scenePlanDialogueRatio: 40,
            scenePlanMode: 'generate_arc_expand',
            scenePlanOutlineCritique: true,
            scenePlanExpandCritique: true,
            scenePlanCloseArc: false,
            minRecommendedNarratorLength: 1024,
        }
    },
    computed: {
        sceneDirectionEnabled() {
            // Effective value — the backend reads scene_direction through
            // resolve_enabled, so a scene override applies here too.
            return effectiveActionEnabled(
                this.agentStatus?.director?.actions,
                this.agentStatus?.director?.scene_overrides,
                'scene_direction',
            );
        },
        charactersMissingActingInstructions() {
            if (!this.sceneCharacters) return [];
            return this.sceneCharacters
                .filter(c => !c.dialogue_instructions)
                .map(c => c.name);
        },
        narratorProgressStoryLength() {
            // fallback 512 matches backend default in NarratorAgent.init_actions()
            return this.agentStatus?.narrator?.actions?.generation_override?.config?.length_progress_story?.value ?? 512;
        },
    },
    methods: {

        requestDirection(params) {
            this.$nextTick(() => {
                this.$refs.instructionsInput.openDialog(params);
            });
        },

        applyDirection(input, params){
            let callback = this[`action${params.action}`];
            if(callback){
                callback({}, input, params);
            }
        },

        // Director actions

        /**
         * Progress the story
         * @method actionRequestDynamicChoices
         * @param {string} instructions - The direction to progress the story in
         */

        actionRequestDynamicChoices(ev, instructions="") {

            if (isPrimaryModifier(ev)) {
                this.requestDirection({action: 'RequestDynamicChoices'});
                return;
            }

            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'director',
                    action: 'request_dynamic_choices',
                    instructions: instructions || "",
                    character: this.getActAsCharacterName(),
                }
            ));
        },

        /**
         * Manually trigger a scene direction turn
         * @method actionSceneDirectionTurn
         * @param {string} instructions - One-off instructions for this turn
         */

        actionSceneDirectionTurn(ev, instructions="") {

            if (isPrimaryModifier(ev)) {
                this.requestDirection({action: 'SceneDirectionTurn'});
                return;
            }

            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'director',
                    action: 'scene_direction_turn',
                    instructions: instructions || "",
                }
            ));
        },

        openScenePlanDialog() {
            this.scenePlanInstructions = '';
            this.scenePlanBeats = 8;
            this.scenePlanMode = 'generate_arc_expand';
            this.scenePlanDialogueRatio = Math.round((this.agentStatus?.director?.actions?.plan?.config?.dialogue_ratio?.value ?? 0.4) * 100);
            this.scenePlanOutlineCritique = this.agentStatus?.director?.actions?.plan?.config?.outline_critique?.value ?? true;
            this.scenePlanExpandCritique = this.agentStatus?.director?.actions?.plan?.config?.expand_critique?.value ?? true;
            // Always reset close_arc to continuation (default) on reopen — no agent-level default for this.
            this.scenePlanCloseArc = false;
            this.scenePlanDialog = true;
        },

        actionCreateScenePlan() {
            this.scenePlanDialog = false;
            this.getWebsocket().send(JSON.stringify({
                type: 'director',
                action: 'chat_create_generate_arc',
                instructions: this.scenePlanInstructions,
                beat_count: this.scenePlanBeats,
                dialogue_ratio: this.scenePlanDialogueRatio / 100,
                mode: this.scenePlanMode,
                outline_critique: this.scenePlanOutlineCritique,
                expand_critique: this.scenePlanExpandCritique,
                close_arc: this.scenePlanCloseArc,
            }));
            this.openDirectorConsole();
        },
    }
}

</script>

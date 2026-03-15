<template>
    <v-dialog v-model="dialog" max-width="600" scrollable>
        <v-card>
            <v-card-title class="d-flex align-center">
                <v-icon class="mr-2" color="warning">mdi-refresh</v-icon>
                Reset Scene State
            </v-card-title>
            <v-card-text>
                <!-- Intro explanation -->
                <v-alert type="warning" variant="tonal" density="compact" class="mb-4">
                    <div class="text-body-2">
                        This is a technical tool for managing scene state. Use it to reset scene progress without affecting character data or world entries.
                    </div>
                    <div class="text-caption mt-1 text-muted">
                        Useful when you encounter unexpected content in your prompts and want to clear cached or accumulated state data.
                    </div>
                </v-alert>

                <v-alert v-if="loading" type="info" variant="tonal" density="compact" class="mb-4">
                    Loading scene state information...
                </v-alert>

                <template v-else>
                    <!-- Context DB -->
                    <v-checkbox
                        v-model="options.resetContextDb"
                        label="Reset Context DB"
                        density="compact"
                        hide-details
                        color="primary"
                    />
                    <div class="text-caption text-muted ml-8 mb-2">
                        The semantic memory database used for context retrieval. Resets and reimports all entries from the scene file.
                    </div>

                    <v-divider class="my-2" />

                    <!-- History -->
                    <v-checkbox
                        v-model="options.wipeHistory"
                        density="compact"
                        hide-details
                        color="primary"
                    >
                        <template #label>
                            Wipe History
                            <span v-if="stateInfo.historyCount > 0" class="text-caption text-muted ml-2">
                                ({{ stateInfo.historyCount }} messages, {{ stateInfo.archivedHistoryCount }} archived, {{ stateInfo.layeredHistoryCount }} layered)
                            </span>
                        </template>
                    </v-checkbox>
                    <div class="text-caption text-muted ml-8 mb-1">
                        Scene messages, archived summaries, and layered history. This is the conversation and narrative progression.
                    </div>
                    <div v-if="options.wipeHistory" class="ml-8">
                        <v-checkbox
                            v-model="options.wipeHistoryIncludeStatic"
                            density="compact"
                            hide-details
                            color="warning"
                        >
                            <template #label>
                                Include static history entries
                                <span v-if="stateInfo.staticHistoryCount > 0" class="text-caption text-muted ml-2">
                                    ({{ stateInfo.staticHistoryCount }} static entries)
                                </span>
                            </template>
                        </v-checkbox>
                        <div class="text-caption text-muted ml-8">
                            Static entries are pre-established backstory not tied to scene progression.
                        </div>
                    </div>

                    <v-divider class="my-2" />

                    <!-- Intent State -->
                    <v-checkbox
                        v-model="options.resetIntentState"
                        label="Reset Intent State"
                        density="compact"
                        hide-details
                        color="primary"
                    />
                    <div class="text-caption text-muted ml-8 mb-2">
                        Scene phase and direction tracking. Controls automatic scene progression behavior.
                    </div>

                    <v-divider class="my-2" />

                    <!-- Agent States -->
                    <v-checkbox
                        v-model="agentStatesEnabled"
                        :indeterminate="agentStatesIndeterminate"
                        density="compact"
                        hide-details
                        color="primary"
                        :disabled="!hasAgentStates"
                    >
                        <template #label>
                            Reset Agent States
                            <span v-if="!hasAgentStates" class="text-caption text-muted ml-2">(no agent states)</span>
                        </template>
                    </v-checkbox>
                    <div class="text-caption text-muted ml-8 mb-1">
                        Cached data and internal state stored by AI agents (director guidance, scene analysis, etc.).
                    </div>
                    <div v-if="hasAgentStates && agentStatesEnabled" class="ml-6 mt-2">
                        <div v-for="(keys, agent) in stateInfo.agentStates" :key="agent" class="mb-2">
                            <v-checkbox
                                v-model="agentEnabled[agent]"
                                :indeterminate="isAgentIndeterminate(agent)"
                                :label="agent"
                                density="compact"
                                hide-details
                                color="primary"
                                @update:model-value="toggleAgent(agent, $event)"
                            />
                            <div v-if="agentEnabled[agent]" class="ml-6">
                                <v-checkbox
                                    v-for="key in keys"
                                    :key="key"
                                    v-model="agentKeys[agent][key]"
                                    :label="key"
                                    density="compact"
                                    hide-details
                                    color="primary"
                                />
                            </div>
                        </div>
                    </div>

                    <v-divider class="my-2" />

                    <!-- Reinforcements -->
                    <v-checkbox
                        v-model="reinforcementsEnabled"
                        :indeterminate="reinforcementsIndeterminate"
                        density="compact"
                        hide-details
                        color="primary"
                        :disabled="!hasReinforcements"
                    >
                        <template #label>
                            Wipe Reinforcements
                            <span v-if="!hasReinforcements" class="text-caption text-muted ml-2">(no reinforcements)</span>
                        </template>
                    </v-checkbox>
                    <div class="text-caption text-muted ml-8 mb-1">
                        Periodic state updates that refresh character or world information at regular intervals.
                    </div>
                    <div v-if="hasReinforcements && reinforcementsEnabled" class="ml-6 mt-2">
                        <v-checkbox
                            v-for="r in stateInfo.reinforcements"
                            :key="r.idx"
                            v-model="reinforcementSelected[r.idx]"
                            density="compact"
                            hide-details
                            color="primary"
                        >
                            <template #label>
                                <v-chip size="x-small" :color="r.character ? 'secondary' : 'primary'" variant="tonal" class="mr-2">
                                    {{ r.character || 'Global' }}
                                </v-chip>
                                <span class="text-caption">{{ truncate(r.question, 50) }}</span>
                            </template>
                        </v-checkbox>
                    </div>
                </template>
            </v-card-text>
            <v-card-actions>
                <v-spacer />
                <v-btn color="muted" variant="text" @click="dialog = false">Cancel</v-btn>
                <v-btn color="warning" variant="tonal" @click="confirmReset" :disabled="!hasSelection || loading">
                    <v-icon class="mr-1">mdi-refresh</v-icon>
                    Reset
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>

    <ConfirmActionPrompt
        ref="confirmDialog"
        @confirm="executeReset"
        actionLabel="Confirm Reset"
        :description="confirmationSummary"
        icon="mdi-alert"
        color="warning"
        :max-width="450"
    />
</template>

<script>
import ConfirmActionPrompt from './ConfirmActionPrompt.vue';

export default {
    name: 'SceneStateResetDialog',
    components: {
        ConfirmActionPrompt,
    },
    inject: ['getWebsocket', 'registerMessageHandler'],
    data() {
        return {
            dialog: false,
            loading: false,
            stateInfo: {
                agentStates: {},
                reinforcements: [],
                historyCount: 0,
                archivedHistoryCount: 0,
                staticHistoryCount: 0,
                layeredHistoryCount: 0,
            },
            options: {
                resetContextDb: false,
                wipeHistory: false,
                wipeHistoryIncludeStatic: false,
                resetIntentState: false,
            },
            // Agent states: two-level selection
            agentEnabled: {},
            agentKeys: {},
            // Reinforcements selection
            reinforcementSelected: {},
        };
    },
    computed: {
        hasAgentStates() {
            return Object.keys(this.stateInfo.agentStates).length > 0;
        },
        hasReinforcements() {
            return this.stateInfo.reinforcements.length > 0;
        },
        agentStatesEnabled: {
            get() {
                if (!this.hasAgentStates) return false;
                return Object.values(this.agentEnabled).some(v => v);
            },
            set(value) {
                for (const agent of Object.keys(this.stateInfo.agentStates)) {
                    this.agentEnabled[agent] = value;
                    if (value) {
                        // Select all keys when enabling agent
                        for (const key of this.stateInfo.agentStates[agent]) {
                            this.agentKeys[agent][key] = true;
                        }
                    }
                }
            }
        },
        agentStatesIndeterminate() {
            if (!this.hasAgentStates) return false;
            const values = Object.values(this.agentEnabled);
            const anyEnabled = values.some(v => v);
            const allEnabled = values.every(v => v);
            return anyEnabled && !allEnabled;
        },
        reinforcementsEnabled: {
            get() {
                if (!this.hasReinforcements) return false;
                return Object.values(this.reinforcementSelected).some(v => v);
            },
            set(value) {
                for (const r of this.stateInfo.reinforcements) {
                    this.reinforcementSelected[r.idx] = value;
                }
            }
        },
        reinforcementsIndeterminate() {
            if (!this.hasReinforcements) return false;
            const values = Object.values(this.reinforcementSelected);
            const anySelected = values.some(v => v);
            const allSelected = values.every(v => v);
            return anySelected && !allSelected;
        },
        hasSelection() {
            return (
                this.options.resetContextDb ||
                this.options.wipeHistory ||
                this.options.resetIntentState ||
                this.agentStatesEnabled ||
                this.reinforcementsEnabled
            );
        },
        confirmationSummary() {
            const items = [];
            if (this.options.resetContextDb) {
                items.push('Reset Context DB');
            }
            if (this.options.wipeHistory) {
                items.push(this.options.wipeHistoryIncludeStatic
                    ? 'Wipe all history (including static)'
                    : 'Wipe history (preserve static)');
            }
            if (this.options.resetIntentState) {
                items.push('Reset Intent State');
            }
            if (this.agentStatesEnabled) {
                const agents = Object.keys(this.agentEnabled).filter(a => this.agentEnabled[a]);
                items.push(`Reset agent states: ${agents.join(', ')}`);
            }
            if (this.reinforcementsEnabled) {
                const count = Object.values(this.reinforcementSelected).filter(v => v).length;
                items.push(`Wipe ${count} reinforcement(s)`);
            }
            return items.length > 0
                ? 'You are about to:\n\n' + items.map(i => '- ' + i).join('\n') + '\n\nThis action cannot be undone.'
                : 'No actions selected.';
        },
    },
    methods: {
        open() {
            this.dialog = true;
            this.resetSelections();
            this.fetchStateInfo();
        },
        resetSelections() {
            this.options = {
                resetContextDb: false,
                wipeHistory: false,
                wipeHistoryIncludeStatic: false,
                resetIntentState: false,
            };
            this.agentEnabled = {};
            this.agentKeys = {};
            this.reinforcementSelected = {};
        },
        fetchStateInfo() {
            this.loading = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_scene_state_reset_info',
            }));
        },
        initializeSelectionState() {
            // Initialize agent state selections
            this.agentEnabled = {};
            this.agentKeys = {};
            for (const [agent, keys] of Object.entries(this.stateInfo.agentStates)) {
                this.agentEnabled[agent] = false;
                this.agentKeys[agent] = {};
                for (const key of keys) {
                    this.agentKeys[agent][key] = false;
                }
            }
            // Initialize reinforcement selections
            this.reinforcementSelected = {};
            for (const r of this.stateInfo.reinforcements) {
                this.reinforcementSelected[r.idx] = false;
            }
        },
        toggleAgent(agent, enabled) {
            if (enabled) {
                // Select all keys when enabling agent
                for (const key of this.stateInfo.agentStates[agent]) {
                    this.agentKeys[agent][key] = true;
                }
            }
        },
        isAgentIndeterminate(agent) {
            const keys = this.stateInfo.agentStates[agent] || [];
            if (keys.length === 0) return false;
            const selectedCount = keys.filter(k => this.agentKeys[agent]?.[k]).length;
            return selectedCount > 0 && selectedCount < keys.length;
        },
        truncate(text, maxLength) {
            if (!text) return '';
            return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
        },
        confirmReset() {
            this.$refs.confirmDialog.initiateAction();
        },
        executeReset() {
            // Build payload
            const payload = {
                reset_context_db: this.options.resetContextDb,
                wipe_history: this.options.wipeHistory,
                wipe_history_include_static: this.options.wipeHistoryIncludeStatic,
                reset_intent_state: this.options.resetIntentState,
                reset_agent_states: {},
                wipe_reinforcements: [],
            };

            // Build agent states to reset
            for (const [agent, enabled] of Object.entries(this.agentEnabled)) {
                if (!enabled) continue;
                const keys = this.stateInfo.agentStates[agent] || [];
                const selectedKeys = keys.filter(k => this.agentKeys[agent]?.[k]);
                if (selectedKeys.length === keys.length) {
                    // All keys selected = reset entire agent
                    payload.reset_agent_states[agent] = true;
                } else if (selectedKeys.length > 0) {
                    payload.reset_agent_states[agent] = selectedKeys;
                }
            }

            // Build reinforcements to wipe
            for (const [idx, selected] of Object.entries(this.reinforcementSelected)) {
                if (selected) {
                    payload.wipe_reinforcements.push(parseInt(idx));
                }
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'execute_scene_state_reset',
                ...payload,
            }));

            this.dialog = false;
        },
        handleMessage(data) {
            if (data.type !== 'world_state_manager') return;

            if (data.action === 'get_scene_state_reset_info') {
                this.stateInfo = {
                    agentStates: data.data.agent_states || {},
                    reinforcements: data.data.reinforcements || [],
                    historyCount: data.data.history_count || 0,
                    archivedHistoryCount: data.data.archived_history_count || 0,
                    staticHistoryCount: data.data.static_history_count || 0,
                    layeredHistoryCount: data.data.layered_history_count || 0,
                };
                this.initializeSelectionState();
                this.loading = false;
            } else if (data.action === 'execute_scene_state_reset') {
                // Reset completed - could show a notification here
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
};
</script>

<style scoped>
.text-muted {
    opacity: 0.7;
}
</style>

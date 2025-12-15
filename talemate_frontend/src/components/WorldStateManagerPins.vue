<template>
    <div :style="{ maxWidth: MAX_CONTENT_WIDTH }">
    <v-card flat>
        <v-card-text>
            <v-row>
                <v-col cols="3">
                    <v-autocomplete
                        :key="autocompleteKey"
                        ref="entryAutocomplete"
                        v-model="selectedEntryId"
                        :items="availableEntries"
                        item-title="title"
                        item-subtitle="subtitle"
                        item-value="id"
                        label="Add pin from world entry"
                        prepend-icon="mdi-plus"
                        density="compact"
                        variant="outlined"
                        clearable
                        @update:model-value="handleEntrySelected"
                        class="mb-2"
                    ></v-autocomplete>
                    <v-list dense v-if="pinsExist" v-model:selected="listSelection" mandatory color="primary">
                        <v-list-item value="info" prepend-icon="mdi-help">
                            <v-list-item-title>Information</v-list-item-title>
                        </v-list-item>
                        <v-list-item v-for="pin in pins" :key="pin.pin.entry_id"
                            :value="pin.pin.entry_id"
                            :prepend-icon="pin.is_active ? 'mdi-pin' : 'mdi-pin-off'"
                            :class="pin.is_active ? '' : 'inactive'">
                            <v-list-item-title>{{ pin.text }}</v-list-item-title>
                            <v-list-item-subtitle>

                            </v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                    <v-card v-else>
                        <v-card-text>
                            No pins defined.
                        </v-card-text>
                    </v-card>
                </v-col>
                <v-col cols="9">
                    <v-row v-if="selected != null && selectedPin != null">
                        <v-col cols="12">
                            <v-card>
                                <v-checkbox v-if="selectedPinIsGamestateControlled" hide-details dense
                                    :model-value="pins[selected].is_active"
                                    :color="pins[selected].is_active ? 'success' : 'delete'"
                                    :class="pins[selected].is_active ? 'pin-active-success' : 'pin-active-delete'"
                                    label="Pin active (computed)" readonly></v-checkbox>
                                <v-checkbox v-else hide-details dense v-model="pins[selected].pin.active"
                                    :color="pins[selected].pin.active ? 'success' : 'delete'"
                                    :class="pins[selected].pin.active ? 'pin-active-success' : 'pin-active-delete'"
                                    label="Pin active" @change="update(selected)"></v-checkbox>
                                <v-alert class="mb-2 pre-wrap" variant="text" color="grey"
                                    icon="mdi-book-open-page-variant">
                                    <div class="formatted-text">
                                        {{ selectedPin.text }}
                                    </div>
                                </v-alert>
                                <v-card-actions>
                                    <ConfirmActionInline action-label="Remove pin" confirm-label="Confirm removal"
                                        @confirm="remove(selected)" />
                                    <v-spacer></v-spacer>
                                    <v-btn variant="text" color="primary"
                                        @click.stop="loadContextDBEntry(selected)"
                                        prepend-icon="mdi-book-open-page-variant">View in context DB</v-btn>
                                </v-card-actions>
                            </v-card>
                        </v-col>
                        <v-col cols="12">
                            <v-card>
                                <v-card-title>
                                    <v-icon size="small">mdi-pin</v-icon> Pin conditions
                                </v-card-title>
                                <v-card-text>
                                    <v-tabs v-model="conditionTab" density="compact" color="secondary">
                                        <v-tab value="ai" prepend-icon="mdi-robot">AI Prompt</v-tab>
                                        <v-tab value="gamestate" prepend-icon="mdi-calculator-variant">Game State</v-tab>
                                    </v-tabs>

                                    <v-window v-model="conditionTab" class="mt-2">
                                        <v-window-item value="ai">
                                            <v-alert v-if="selectedPinIsGamestateControlled" variant="text" color="grey" icon="mdi-information-outline">
                                                Game State conditions are set, so the AI prompt condition is currently ignored (but kept for later).
                                            </v-alert>

                                            <v-textarea rows="1" auto-grow
                                                v-model="pins[selected].pin.condition"
                                                label="Condition question prompt for auto pinning"
                                                hint="Evaluated by the World State agent regularly. Use a question the AI can answer with yes/no."
                                                @blur="update(selected)">
                                            </v-textarea>

                                            <v-slider
                                                min="0"
                                                max="100"
                                                step="1"
                                                v-model="pins[selected].pin.decay"
                                                label="Decay"
                                                thumb-label="always"
                                                hint="Number of rounds this pin stays active once activated. 0 means no decay. You do NOT need to set a condition for this to work."
                                                @change="update(selected)"
                                            />
                                            <v-slider v-if="pins[selected].pin.decay_due > 0"
                                                min="0"
                                                :max="pins[selected].pin.decay"
                                                step="1"
                                                color="brown-darken-2"
                                                v-model="pins[selected].pin.decay_due"
                                                label="Active decay counter"
                                                thumb-label="always"
                                                hint="Active decay counter for this pin."
                                                @change="update(selected)"
                                            />
                                            <v-checkbox hide-details dense v-model="pins[selected].pin.condition_state"
                                                label="Current condition evaluation"
                                                @change="update(selected)"></v-checkbox>
                                        </v-window-item>

                                        <v-window-item value="gamestate">
                                            <WorldStateManagerPinConditionGroups
                                                :readonly="false"
                                                :model-value="pins[selected].pin.gamestate_condition || []"
                                                @update:model-value="setGamestateCondition(selected, $event)"
                                            />
                                        </v-window-item>
                                    </v-window>
                                </v-card-text>
                                <v-card-actions v-if="conditionTab === 'gamestate'">
                                    <v-btn variant="text" color="primary" prepend-icon="mdi-gamepad-square"
                                        @click="navigateToGameStateEditor">
                                        Open Game State Editor
                                    </v-btn>
                                </v-card-actions>
                            </v-card>
                        </v-col>


                    </v-row>
                    <v-alert v-else type="info" color="grey" variant="text" icon="mdi-pin">
                        Pins allow you to permanently pin a context entry to the AI context. While a pin is
                        active, the AI will always consider the pinned entry when generating text. <v-icon
                            color="warning">mdi-alert</v-icon> Pinning too many entries may use up your
                        available context size, so use them wisely.

                        <br><br>
                        Additionally you may also define auto pin conditions that will automatically pin or unpin entries:
                        <br><br>
                        • <strong>AI Prompt conditions:</strong> The World State agent will check these every turn using natural language questions. If the condition is met, the entry will be pinned. If the condition is no longer met, the entry will be unpinned.
                        <br><br>
                        • <strong>Game State conditions:</strong> These check game state variables directly (e.g., "quest/stage", "character/mood"). When game state conditions are set, the pin becomes fully automated and cannot be manually toggled. The pin will automatically activate or deactivate based on the current game state values.

                        <br><br>
                        Finally, remember there is also automatic insertion of context based on relevance to
                        the current scene progress, which happens regardless of pins. Pins are just a way to
                        ensure that a specific entry is always considered relevant.

                    </v-alert>

                </v-col>
            </v-row>
        </v-card-text>
    </v-card>
    </div>
</template>

<script>
import { MAX_CONTENT_WIDTH } from '@/constants';
import ConfirmActionInline from './ConfirmActionInline.vue';
import WorldStateManagerPinConditionGroups from './WorldStateManagerPinConditionGroups.vue';

export default {
    name: 'WorldStateManagerPins',
    components: {
        ConfirmActionInline,
        WorldStateManagerPinConditionGroups,
    },
    data() {
        return {
            pins: {},
            selected: null,
            updateTimeout: null,
            conditionTab: 'ai',
            MAX_CONTENT_WIDTH,
            selectedEntryId: null,
            autocompleteKey: 0,
            listSelection: ['info'],
        }
    },
    emits:[
        'require-scene-save',
        'world-state-manager-navigate',
    ],
    props: {
        immutablePins: Object,
        worldEntries: {
            type: Object,
            default: () => ({}),
        },
    },
    watch: {
        immutablePins: {
            immediate: true,
            handler(value) {
                if (!value) {
                    this.pins = null;
                } else {
                    this.pins = { ...value };
                }
            }
        },
        listSelection: {
            handler(value) {
                // Handle list selection changes from user interaction
                if (Array.isArray(value) && value.length > 0) {
                    const selectedValue = value[0];
                    if (selectedValue === 'info') {
                        this.selected = null;
                    } else {
                        if (this.selected !== selectedValue) {
                            this.selectPin(selectedValue);
                        }
                    }
                } else {
                    this.selected = null;
                }
            }
        }
    },
    computed: {
        selectedPin() {

            if (this.selected === null) {
                return null;
            }

            if (!this.pins) {
                return null;
            }

            return this.pins[this.selected];
        },
        selectedPinIsGamestateControlled() {
            if (!this.selectedPin || !this.selectedPin.pin) return false;
            const gs = this.selectedPin.pin.gamestate_condition;
            return Array.isArray(gs) && gs.length > 0;
        },
        pinsExist() {
            if (!this.pins) return false;
            return Object.keys(this.pins).length > 0;
        },
        availableEntries() {
            if (!this.worldEntries) return [];
            
            const entries = [];
            for (const [id, entry] of Object.entries(this.worldEntries)) {
                // Filter out entries that already have pins
                if (!this.entryHasPin(id)) {
                    // Create a preview of the text (first 50 chars)
                    const textPreview = entry.text ? entry.text.substring(0, 50) : '';
                    entries.push({
                        id: id,
                        title: id,
                        subtitle: textPreview + (entry.text && entry.text.length > 50 ? '...' : ''),
                    });
                }
            }
            return entries.sort((a, b) => a.title.localeCompare(b.title));
        },
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'loadContextDBEntry',
    ],
    methods: {

        reset() {
            this.selected = null;
            this.pins = {};
        },

        entryHasPin(entryId) {
            return this.pins[entryId] !== undefined;
        },

        entryIsPinned(entryId) {
            return this.entryHasPin(entryId) && this.pins[entryId].is_active;
        },

        selectPin(entryId) {
            if (this.selected !== entryId) {
                this.selected = entryId;
                // Update list selection to sync with Vuetify list
                this.listSelection = [entryId];
                // default tab based on current mode
                const gs = this.pins?.[entryId]?.pin?.gamestate_condition;
                const isGamestate = Array.isArray(gs) && gs.length > 0;
                if (isGamestate) {
                    this.conditionTab = 'gamestate';
                } else {
                    this.conditionTab = 'ai';
                }
            }
        },

        add(entryId) {

            this.pins[entryId] = {
                text: "",
                is_active: false,
                pin: {
                    entry_id: entryId,
                    active: false,
                    condition: "",
                    condition_state: false,
                    gamestate_condition: null,
                    decay: 0,
                    decay_due: 0,
                }
            };
            this.selectPin(entryId);

            this.update(entryId);
        },

        remove(entryId) {
            delete this.pins[entryId];
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'remove_pin',
                entry_id: entryId,
            }));
            this.selected = null;
            this.removeConfirm = false;
        },

        update(entryId) {

            let pin = this.pins[entryId];

            if(pin === undefined) {
                return;
            }

            const gs = pin.pin.gamestate_condition;
            const hasGs = Array.isArray(gs) && gs.length > 0;

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_pin',
                entry_id: pin.pin.entry_id,
                active: pin.pin.active,
                condition: pin.pin.condition,
                condition_state: pin.pin.condition_state,
                gamestate_condition: hasGs ? gs : null,
                decay: (pin.pin.decay && pin.pin.decay > 0) ? pin.pin.decay : null,
            }));
        },

        queueUpdate(pin) {
            if (this.updateTimeout !== null) {
                clearTimeout(this.updateTimeout);
            }

            this.updateTimeout = setTimeout(() => {
                this.update(pin);
            }, 500);
        },


        setGamestateCondition(entryId, groups) {
            if (!this.pins || !this.pins[entryId]) return;
            const normalized = Array.isArray(groups) ? groups : [];
            const hasGs = normalized.length > 0;

            this.pins[entryId].pin.gamestate_condition = hasGs ? normalized : null;

            this.update(entryId);
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
        },
        handleEntrySelected(entryId) {
            if (entryId && !this.entryHasPin(entryId)) {
                this.add(entryId);
            }
            // Always clear the autocomplete selection by resetting the key to force re-render
            this.selectedEntryId = null;
            this.autocompleteKey += 1;
        },
        navigateToGameStateEditor() {
            this.$emit('world-state-manager-navigate', 'scene', 'gamestate');
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>

<style scoped>
.formatted-text {
    white-space: pre-wrap;
}

.pin-active-success :deep(.v-checkbox .v-icon),
.pin-active-success :deep(.v-selection-control__input .v-icon) {
    color: rgb(var(--v-theme-success)) !important;
}

.pin-active-success :deep(.v-checkbox .mdi-checkbox-blank-outline),
.pin-active-success :deep(.v-selection-control__input .mdi-checkbox-blank-outline) {
    color: rgb(var(--v-theme-success)) !important;
    opacity: 1 !important;
}

.pin-active-delete :deep(.v-checkbox .v-icon),
.pin-active-delete :deep(.v-selection-control__input .v-icon) {
    color: rgb(var(--v-theme-delete)) !important;
}

.pin-active-delete :deep(.v-checkbox .mdi-checkbox-blank-outline),
.pin-active-delete :deep(.v-selection-control__input .mdi-checkbox-blank-outline) {
    color: rgb(var(--v-theme-delete)) !important;
    opacity: 1 !important;
}

</style>
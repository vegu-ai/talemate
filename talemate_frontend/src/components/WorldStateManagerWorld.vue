<template>

    <v-card flat>
        <v-overlay contained v-model="busy"></v-overlay>

        <v-card-text>
            <!-- ENTRIES -->
            <v-toolbar density="compact" color="grey-darken-4">
                <v-spacer></v-spacer>
                <v-btn rounded="sm" prepend-icon="mdi-format-list-text" @click.stop="selectedPage='entries'">
                    Entries
                </v-btn>
                <v-btn rounded="sm" prepend-icon="mdi-image-auto-adjust" @click.stop="selectedPage='states'">
                    States
                </v-btn>
            </v-toolbar>
            <div v-if="selectedPage == 'entries'">

                <v-row color="grey-darken-5">
                    <v-col cols="3">
                        <v-text-field v-model="filter" label="Filter entries" append-inner-icon="mdi-magnify" clearable
                        density="compact" variant="underlined" class="ml-1 mb-1"></v-text-field>
                    </v-col>
                    <v-col cols="5" class="text-right">
    
                    </v-col>
                    <v-col cols="4">
                        <v-text-field v-model="newEntryId" label="New entry" append-inner-icon="mdi-plus" class="mr-1 mb-1"
                        variant="underlined" density="compact" hint="Enter a name for a new entry. (Enter to create)"
                        @keyup.enter="createEntry" :rules="[validateEntryId]"></v-text-field>
                    </v-col>
                </v-row>
                <v-divider></v-divider>
                <v-row>
                    <v-col cols="3">
                        <v-list>
                            <v-list-subheader>Entries</v-list-subheader>
                            <v-list-item v-for="(entry, index) in filteredEntries()" :key="index"
                                @click="selectEntry(index)">
                                <v-list-item-title>{{ entry.id }}</v-list-item-title>
                                <v-list-item-subtitle>
                                    {{ entry.text }}
                                </v-list-item-subtitle>
                            </v-list-item>
                        </v-list>
                    </v-col>
                    <v-col cols="9">
                        <div v-if="selectedEntryId === null">
                            <v-alert type="info" color="grey" variant="text" icon="mdi-earth">
                                Add world information / lore and add extra details.
                                <br><br>
                                You can also set up automatic reinforcement of world information states. This will cause the AI to regularly re-evaluate the state and update the detail accordingly.
                                <br><br>
                                Add a new entry or select an existing one to get started.
                                <br><br>
                                <v-icon color="orange" class="mr-1">mdi-alert</v-icon> If you want to add details to an acting character do that through the character manager instead.
                            </v-alert>
                        </div>
                        <v-card v-else>
                            <v-card-title>
                                <v-icon size="small">mdi-earth</v-icon>
                                {{ entry.id }}
                            </v-card-title>
                            <v-card-text>
                                <v-row>
                                    <v-col cols="12">
                                        <ContextualGenerate 
                                            :context="'world context:'+entry.id" 
                                            :original="entry.text"
                                            @generate="content => { entry.text=content; queueSaveEntry(); }"
                                        />
                                        <v-textarea 
                                            v-model="entry.text"
                                            label="World information"
                                            hint="Describe the world information here. This could be a description of a location, a historical event, or anything else that is relevant to the world." 
                                            :color="dirty ? 'info' : ''"
                                            @update:model-value="queueSaveEntry"
                                            auto-grow
                                            rows="5">
                                        </v-textarea>
                                        <v-checkbox v-model="entry.meta['pin_only']" 
                                        label="Include only when pinned" 
                                        :hint="(
                                            entry.meta['pin_only'] ? 
                                            'This entry will only be included when pinned and never be included via automatic relevancy matching.' :
                                            'This entry may be included via automatic relevancy matching.'
                                        )"
                                        @change="queueSaveEntry"></v-checkbox>
                                    </v-col>
                                </v-row>
    
                            </v-card-text>
                            <v-card-actions>
                                <span v-if="deleteConfirm===false">
                                    <v-btn rounded="sm" prepend-icon="mdi-close-box-outline" color="error" variant="text" @click.stop="deleteConfirm=true" >
                                        Remove entry
                                    </v-btn>
                                </span>
                                <span v-else>
                                    <v-btn rounded="sm" prepend-icon="mdi-close-box-outline" @click.stop="removeEntry"  color="error" variant="text">
                                        Confirm removal
                                    </v-btn>
                                    <v-btn class="ml-1" rounded="sm" prepend-icon="mdi-cancel" @click.stop="deleteConfirm=false" color="info" variant="text">
                                        Cancel
                                    </v-btn>
                                </span>
                                <v-spacer></v-spacer>
                                <v-btn variant="text" color="primary" @click.stop="loadContextDBEntry(entry.id)" prepend-icon="mdi-book-open-page-variant">View in context DB</v-btn>
                                
                                <v-btn v-if="!entryHasPin(entry.id)" rounded="sm" prepend-icon="mdi-pin" @click.stop="addPin(entry.id)" color="primary" variant="text">
                                    Create Pin
                                </v-btn>
                                <v-btn v-else rounded="sm" prepend-icon="mdi-pin" @click.stop="selectPin(entry.id)" color="primary" variant="text">
                                    Manage Pin
                                </v-btn>
                               
                            </v-card-actions>
                        </v-card>
                    </v-col>
                </v-row>
            </div>

            <div v-else-if="selectedPage == 'states'">
                <v-row color="grey-darken-5">
                    <v-col cols="3">
                        <v-text-field v-model="filterState" label="Filter states" append-inner-icon="mdi-magnify" clearable
                        density="compact" variant="underlined" class="ml-1 mb-1"></v-text-field>
                    </v-col>
                    <v-col cols="5" class="text-right">
    
                    </v-col>
                    <v-col cols="4">
                        <v-text-field v-model="newStateQuery" label="New state" append-inner-icon="mdi-plus" class="mr-1 mb-1"
                        variant="underlined" density="compact" hint="Enter a question or an attribute name."
                        @keyup.enter="createState"></v-text-field>
                    </v-col>
                </v-row>
                <v-divider></v-divider>
                <v-row>
                    <v-col cols="3">
                        <v-list>
                            <v-list-subheader>States</v-list-subheader>
                            <v-list-item v-for="(state, index) in filteredStates()" :key="index"
                                @click="selectState(index)">
                                <v-list-item-title>{{ state.question }}</v-list-item-title>
                                <v-list-item-subtitle>
                                    <v-chip size="x-small" label color="info" variant="outlined">update in {{ state.due }} turns</v-chip>
                                </v-list-item-subtitle>
                            </v-list-item>
                        </v-list>
                    </v-col>
                    <v-col cols="9">
                        <div v-if="selectedPage == 'states'">
                            <div v-if="selectedStateQuery === null">
                                <v-alert type="info" color="grey" variant="text" icon="mdi-earth">
                                    Set up automatic reinforcement of world information states. This will cause the AI to regularly re-evaluate the state and update the detail accordingly.
                                    <br><br>
                                    Add a new state or select an existing one to get started.
                                    <br><br>
                                    <v-icon color="orange" class="mr-1">mdi-alert</v-icon> If you want to track states for an acting character, do that through the character manager instead.
                                </v-alert>
                            </div>
                            <v-card v-else>
                                <v-card-text>
                                    <v-row>
                                        <v-col cols="12">
                                            <v-textarea 
                                                v-model="state.answer"
                                                :label="state.question"
                                                :color="dirty ? 'info' : ''"
                                                @update:model-value="queueSaveState"
                                                max-rows="15"
                                                auto-grow
                                                rows="5">
                                            </v-textarea>
                                        </v-col>
                                    </v-row>

                                    <v-row>
                                        <v-col cols="6">
                                            <v-text-field v-model="state.interval" label="Re-inforce / Update detail every N turns" type="number" min="1" max="100" step="1" class="mb-2" @update:modelValue="queueSaveState" :color="dirty ? 'info' : ''"></v-text-field>
                                        </v-col>
                                        <v-col cols="6">
                                            <v-select 
                                                v-model="state.insert" :items="insertionModes" 
                                                label="Context Attachment Method" 
                                                class="mr-1 mb-1" 
                                                variant="underlined"  
                                                density="compact" @update:modelValue="queueSaveState" :color="dirty ? 'info' : ''">
                                            </v-select>
                                        </v-col>
                                    </v-row>

                                    <v-row>
                                        <v-col cols="12">
                                            <v-textarea 
                                                v-model="state.instructions"
                                                label="Additional instructions to the AI for generating this state."
                                                :color="dirty ? 'info' : ''"
                                                @update:model-value="queueSaveState"
                                                auto-grow
                                                max-rows="5"
                                                rows="3">
                                            </v-textarea>
                                        </v-col>
                                    </v-row>

                                </v-card-text>
                                <v-card-actions>
                                    <span v-if="deleteConfirm===false">
                                        <v-btn rounded="sm" prepend-icon="mdi-close-box-outline" color="error" variant="text" @click.stop="deleteConfirm=true" >
                                            Remove state
                                        </v-btn>
                                    </span>
                                    <span v-else>
                                        <v-btn rounded="sm" prepend-icon="mdi-close-box-outline" @click.stop="removeState"  color="error" variant="text">
                                            Confirm removal
                                        </v-btn>
                                        <v-btn class="ml-1" rounded="sm" prepend-icon="mdi-cancel" @click.stop="deleteConfirm=false" color="info" variant="text">
                                            Cancel
                                        </v-btn>
                                    </span>
                                    <v-spacer></v-spacer>
                                    <v-tooltip text="Removes all previously generated reinforcements for this state and then regenerates it">
                                        <template v-slot:activator="{ props }">
                                            <v-btn v-if="resetStateReinforcerConfirm === true" v-bind="props" rounded="sm" prepend-icon="mdi-backup-restore" @click.stop="runStateReinforcement(true)" color="warning" variant="text">
                                                Confirm Reset State
                                            </v-btn>
                                            <v-btn v-else v-bind="props" rounded="sm" prepend-icon="mdi-backup-restore" @click.stop="resetStateReinforcerConfirm=true" color="warning" variant="text">
                                                Reset State
                                            </v-btn>
                                        </template> 
                                    </v-tooltip>
                                    <v-btn rounded="sm" prepend-icon="mdi-refresh" @click.stop="runStateReinforcement()" color="primary" variant="text">
                                        Refresh State
                                    </v-btn>
                                </v-card-actions>
                            </v-card>
                        </div>
                    </v-col>
                </v-row>
            </div>
            
            
            <!-- STATES -->


        </v-card-text>
    </v-card>
</template>

<script>

import ContextualGenerate from './ContextualGenerate.vue';

export default {
    name: 'WorldStateManagerWorld',
    components: {
        ContextualGenerate,
    },
    props: {
        pins: Object
    },
    data() {
        return {
            entries: {},
            reinforcements: {},
            filter: null,
            filterState: null,
            newEntryId: null,
            newStateQuery: null,
            selectedEntryId: null,
            selectedStateQuery: null,
            selectedPage: 'entries',
            saveEntryTimeout: null,
            deleteConfirm: false,
            deferedNavigation: null,
            resetStateReinforcerConfirm: false,
            dirty: false,
            busy: false,
            baseEntry: {
                id: '',
                text: '',
                ts: '',
                meta: {
                    pin_only: false,
                },
            },
            entry: {
                id: '',
                text: '',
                ts: '',
                meta: {
                    pin_only: false,
                },
            },
            baseState: {
                question: '',
                instructions: '',
                interval: 10,
                answer: '',
                insert: 'never',
            },
            state: {
                question: '',
                instructions: '',
                interval: 10,
                answer: '',
                insert: 'never',
            },
        };
    },
    inject: [
        'insertionModes',
        'getWebsocket',
        'registerMessageHandler',
        'setWaitingForInput',
        'openCharacterSheet',
        'characterSheet',
        'isInputDisabled',
        'insertionModes',
        'loadContextDBEntry',
    ],
    watch:{
        entries() {
            if(this.deferedNavigation !== null && this.deferedNavigation[0] === 'entries') {
                this.$nextTick().then(() => {
                    this.selectedPage = 'entries';
                    this.selectEntry(this.deferedNavigation[1]);
                    this.deferedNavigation = null;
                });
            }
        },
        reinforcements() {
            if(this.deferedNavigation !== null && this.deferedNavigation[0] === 'states') {
                this.$nextTick().then(() => {
                    this.selectedPage = 'states';
                    this.selectState(this.deferedNavigation[1]);
                    this.deferedNavigation = null;
                });
            }
        }
    },
    emits:[
        'require-scene-save',
        'load-pin',
        'add-pin',
        'request-sync',
    ],
    methods: {

        reset() {
            this.selectedEntryId = null;
            this.selectedStateQuery = null;
            this.entry = null;
            this.state = null;
        },

        navigate(page, stateOrEntryId) {
            this.$nextTick().then(() => {
                this.requestWorld();
                this.deferedNavigation = [page, stateOrEntryId];
            });
        },

        // pins
        entryHasPin(entryId) {
            return this.pins[entryId] !== undefined;
        },

        selectPin(entryId) {
            this.$emit('load-pin', entryId);
        },

        addPin(entryId) {
            this.$emit('add-pin', entryId)
        },

        entryIsPinned(entryId) {
            return this.entryHasPin(entryId) && this.pins[entryId].pin.active;
        },

        // entries
        validateEntryId(value) {
            if(value == null)
                return true;
            
            // no special characters, return false if there are any
            if(value.match(/[^a-zA-Z0-9_ ]/)) {
                return "No special characters allowed";
            }
            return true
        },
        filteredEntries() {
            if (!this.filter) {
                return this.entries;
            }

            let result = {};
            for (let key in this.entries) {
                if (this.entries[key].id.toLowerCase().includes(this.filter.toLowerCase())) {
                    result[key] = this.entries[key];
                }
            }
            return result;
        },
        selectEntry(entryId) {
            this.selectedEntryId = entryId;
            this.entry = this.entries[entryId];
        },

        createEntry() {
            if (this.newEntryId === null || this.newEntryId === '') {
                return;
            }

            if(this.validateEntryId(this.newEntryId) !== true) {
                return;
            }

            // copy the base template

            let newEntry = JSON.parse(JSON.stringify(this.baseEntry));
            newEntry.id = this.newEntryId;

            this.entries[this.newEntryId] = newEntry;
            this.selectEntry(this.newEntryId);

            this.newEntryId = null;
        },

        // states

        filteredStates() {
            if (!this.filterState) {
                return this.reinforcements;
            }

            let result = {};
            for (let key in this.reinforcements) {
                if (this.reinforcements[key].question.toLowerCase().includes(this.filterState.toLowerCase())) {
                    result[key] = this.reinforcements[key];
                }
            }
            return result;
        },

        selectState(query) {
            this.selectedStateQuery = query;
            this.state = this.reinforcements[query];
        },

        createState() {
            if (this.newStateQuery === null || this.newStateQuery === '') {
                return;
            }

            // copy the base template

            let newState = JSON.parse(JSON.stringify(this.baseState));
            newState.question = this.newStateQuery;

            this.reinforcements[this.newStateQuery] = newState;
            this.selectState(this.newStateQuery);
            this.newStateQuery = null;

            this.saveState(true);
        },

        // queue requests
        queueSaveEntry() {
            if (this.saveEntryTimeout !== null) {
                clearTimeout(this.saveEntryTimeout);
            }

            this.dirty = true;

            this.saveEntryTimeout = setTimeout(() => {
                this.saveEntry();
            }, 500);
        },

        queueSaveState() {
            if (this.saveStateTimeout !== null) {
                clearTimeout(this.saveStateTimeout);
            }

            this.dirty = true;

            this.saveStateTimeout = setTimeout(() => {
                this.saveState();
            }, 500);
        },

        // requests 
        saveEntry() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_world_entry',
                id: this.entry.id,
                text: this.entry.text,
                meta: this.entry.meta,
            }));
        },

        saveState(updateState) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_world_state_reinforcement',
                question: this.state.question,
                answer: this.state.answer,
                instructions: this.state.instructions,
                interval: this.state.interval,
                insert: this.state.insert,
                update_state: updateState,
            }));

            if(updateState) {
                this.busy = true;
            }
        },

        removeEntry() {
            this.deleteConfirm = false;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_world_entry',
                id: this.entry.id
            }));
        },
        
        removeState() {
            this.deleteConfirm = false;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_world_state_reinforcement',
                question: this.state.question
            }));
        },

        runStateReinforcement(reset) {
            this.busy=true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'run_world_state_reinforcement',
                question: this.state.question,
                reset: reset || false,
            }));

            this.resetStateReinforcerConfirm = false;
        },

        requestWorld: function () {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_world',
            }));
        },

        // responses
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action == 'world') {
                this.entries = message.data.entries;
                this.reinforcements = message.data.reinforcements;

                if(this.selectedEntryId !== null) {
                    this.entry = this.entries[this.selectedEntryId];
                }
                if(this.selectedStateQuery !== null) {
                    this.state = this.reinforcements[this.selectedStateQuery];
                }
            } else if (message.action == 'world_entry_saved') {
                this.dirty = false;
            } else if (message.action == 'world_entry_deleted') {
                this.selectedEntryId = null;
            } else if (message.action == 'world_state_reinforcement_set') {
                this.dirty = false;
                this.requestWorld();
            } else if (message.action == 'world_state_reinforcement_deleted') {
                this.selectedStateQuery = null;
            } else if (message.action == 'world_state_reinforcement_ran') {
                this.busy = false;
            } else if(message.action === 'operation_done') {
                this.busy = false;
            }
        },
    },
    mounted(){
        this.requestWorld();
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
};
</script>
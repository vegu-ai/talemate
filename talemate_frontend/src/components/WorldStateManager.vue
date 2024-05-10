<template>
    <v-overlay contained v-model="isBusy"></v-overlay>
    <v-card variant="text">
        <v-window v-model="tab">

            <!-- CHARACTERS -->

            <v-window-item value="characters">
                <WorldStateManagerCharacter 
                ref="characters" 
                @require-scene-save="requireSceneSave = true"
                :templates="templates"
                :character-list="characterList" />
            </v-window-item>

            <!-- WORLD -->

            <v-window-item value="world">
                <WorldStateManagerWorld ref="world" />
            </v-window-item>

            <!-- HISTORY -->

            <v-window-item value="history">
                <v-card flat>
                    <v-card-text>
                        <div>
                            <!-- Placeholder for History content -->
                        </div>
                    </v-card-text>
                </v-card>
            </v-window-item>

            <!-- CONTEXT DB -->

            <v-window-item value="contextdb">
                <v-card flat>
                    <v-card-text>
                        <v-toolbar floating density="compact" class="mb-2" color="grey-darken-4">
                            <v-text-field v-model="contextDBQuery" label="Content search"
                                append-inner-icon="mdi-magnify" clearable single-line hide-details density="compact"
                                variant="underlined" class="ml-1 mb-1 mr-1"
                                @keyup.enter="queryContextDB"></v-text-field>

                            <v-select v-model="contextDBQueryMetaKey" :items="contextDBMetaKeys" label="Filter By Tag"
                                class="mr-1 mb-1" variant="underlined" single-line hide-details
                                density="compact"></v-select>
                            <v-select
                                v-if="contextDBQueryMetaKey !== null && contextDBMetaValuesByType[contextDBQueryMetaKey]"
                                v-model="contextDBQueryMetaValue"
                                :items="contextDBMetaValuesByType[contextDBQueryMetaKey]()" label="Tag value"
                                class="mr-1 mb-1" variant="underlined" single-line hide-details
                                density="compact"></v-select>
                            <v-text-field v-else v-model="contextDBQueryMetaValue" label="Tag value" class="mr-1 mb-1"
                                variant="underlined" single-line hide-details density="compact"></v-text-field>
                            <v-spacer></v-spacer>
                            <!-- button that opens the tools menu -->
                            <v-menu>
                                <template v-slot:activator="{ props }">
                                    <v-btn rounded="sm" v-bind="props" prepend-icon="mdi-tools" variant="text">
                                        Tools
                                    </v-btn>
                                </template>
                                <v-list>
                                    <v-list-item @click.stop="resetContextDB" append-icon="mdi-shield-alert">
                                        <v-list-item-title>Reset</v-list-item-title>
                                    </v-list-item>
                                </v-list>
                            </v-menu>

                            <!-- button to open add content db entry dialog -->
                            <v-btn rounded="sm" prepend-icon="mdi-plus" @click.stop="dialogAddContextDBEntry = true"
                                variant="text">
                                Add entry
                            </v-btn>
                        </v-toolbar>
                        <v-divider></v-divider>
                        <!-- add entry-->
                        <v-card v-if="dialogAddContextDBEntry === true">
                            <v-card-title>
                                Add entry
                            </v-card-title>
                            <v-card-text>
                                <v-row>
                                    <v-col cols="12">
                                        <v-textarea rows="5" auto-grow v-model="newContextDBEntryText" label="Content"
                                            hint="The content of the entry."></v-textarea>
                                    </v-col>
                                </v-row>
                                <v-row>
                                    <v-col cols="12">
                                        <v-chip v-for="(value, name) in newContextDBEntryMeta" :key="name" label
                                            size="x-small" variant="outlined" class="ml-1" closable
                                            @click:close="handleRemoveContextDBEntryMeta(name)">{{ name }}: {{ value
                                            }}</v-chip>
                                    </v-col>
                                </v-row>
                                <v-row>
                                    <v-col cols="3">
                                        <v-select v-model="newContextDBEntryMetaKey" :items="contextDBMetaKeys"
                                            label="Meta key" class="mr-1 mb-1" variant="underlined" single-line
                                            hide-details density="compact"></v-select>
                                    </v-col>
                                    <v-col cols="3">
                                        <v-select
                                            v-if="newContextDBEntryMetaKey !== null && contextDBMetaValuesByType[newContextDBEntryMetaKey]"
                                            v-model="newContextDBEntryMetaValue"
                                            :items="contextDBMetaValuesByType[newContextDBEntryMetaKey]()"
                                            label="Meta value" class="mr-1 mb-1" variant="underlined" single-line
                                            hide-details density="compact"></v-select>
                                        <v-text-field v-else v-model="newContextDBEntryMetaValue" label="Meta value"
                                            class="mr-1 mb-1" variant="underlined" single-line hide-details
                                            density="compact"></v-text-field>
                                    </v-col>
                                    <v-col cols="3">
                                        <v-btn rounded="sm" color="primary" prepend-icon="mdi-plus"
                                            @click.stop="handleNewContextDBEntryMeta" variant="text">
                                            Add meta
                                        </v-btn>
                                    </v-col>
                                </v-row>
                            </v-card-text>
                            <v-card-actions>
                                <!-- cancel -->
                                <v-btn rounded="sm" prepend-icon="mdi-cancel"
                                    @click.stop="dialogAddContextDBEntry = false" color="info" variant="text">
                                    Cancel
                                </v-btn>
                                <v-spacer></v-spacer>
                                <!-- add -->
                                <v-btn rounded="sm" prepend-icon="mdi-plus" @click.stop="addContextDBEntry"
                                    color="primary" variant="text">
                                    Add
                                </v-btn>
                            </v-card-actions>
                        </v-card>

                        <!-- results -->
                        <div v-else>
                            <v-table height="600px" v-if="contextDB.entries.length > 0">
                                <thead>
                                    <tr>
                                        <th class="text-left"></th>
                                        <th class="text-left" width="60%">Content</th>
                                        <th class="text-center">Pin</th>
                                        <th class="text-left">Tags</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="entry in contextDB.entries" :key="entry.id">
                                        <td>
                                            <!-- remove -->
                                            <v-tooltip text="Delete entry">
                                                <template v-slot:activator="{ props }">
                                                    <v-btn icon size="x-small" v-bind="props" rounded="sm"
                                                        variant="text" color="red-darken-1"
                                                        @click.stop="deleteContextDBEntry(entry.id)">
                                                        <v-icon>mdi-close-box-outline</v-icon>
                                                    </v-btn>
                                                </template>
                                            </v-tooltip>
                                        </td>
                                        <td>
                                            <v-textarea rows="1" auto-grow density="compact" hide-details
                                                :color="entry.dirty ? 'info' : ''" v-model="entry.text"
                                                @update:model-value="queueUpdateContextDBEntry(entry)"></v-textarea>
                                        </td>
                                        <td class="text-center">
                                            <v-tooltip :text="entryHasPin(entry.id) ? 'Manage pin' : 'Add pin'">
                                                <template v-slot:activator="{ props }">
                                                    <v-btn v-bind="props" size="x-small" rounded="sm" variant="text"
                                                        v-if="entryIsPinned(entry.id)" color="success" icon
                                                        @click.stop="selectPin(entry.id)"><v-icon>mdi-pin</v-icon></v-btn>
                                                    <v-btn v-bind="props" size="x-small" rounded="sm" variant="text"
                                                        v-else-if="entryHasPin(entry.id)" color="red-darken-2" icon
                                                        @click.stop="selectPin(entry.id)"><v-icon>mdi-pin</v-icon></v-btn>
                                                    <v-btn v-bind="props" size="x-small" rounded="sm" variant="text"
                                                        v-else color="grey-lighten-2" icon
                                                        @click.stop="addPin(entry.id)"><v-icon>mdi-pin</v-icon></v-btn>
                                                </template>
                                            </v-tooltip>

                                        </td>
                                        <td>
                                            <!-- render entry.meta as v-chip elements showing both name and value -->
                                            <v-chip v-for="(value, name) in visibleMetaTags(entry.meta)" :key="name"
                                                label size="x-small" variant="outlined" class="ml-1">{{ name }}: {{
                                                    value }}</v-chip>
                                        </td>
                                    </tr>
                                </tbody>
                            </v-table>
                            <v-alert v-else-if="contextDBCurrentQuery" dense type="warning" variant="text"
                                icon="mdi-information-outline">
                                No results
                            </v-alert>
                            <v-alert v-else dense type="info" variant="text" icon="mdi-magnify">
                                Enter a query to search the context database.
                            </v-alert>
                        </div>

                    </v-card-text>
                </v-card>
            </v-window-item>

            <!-- PINS -->

            <v-window-item value="pins">
                <v-card flat>
                    <v-card-text>
                        <v-row>
                            <v-col cols="3">
                                <v-list dense v-if="pinsExist()">
                                    <v-list-item prepend-icon="mdi-help" @click.stop="selectedPin = null">
                                        <v-list-item-title>Information</v-list-item-title>
                                    </v-list-item>
                                    <v-list-item v-for="pin in pins" :key="pin.pin.entry_id"
                                        @click.stop="selectedPin = pin"
                                        :prepend-icon="pin.pin.active ? 'mdi-pin' : 'mdi-pin-off'"
                                        :class="pin.pin.active ? '' : 'inactive'">
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
                                <v-row v-if="selectedPin !== null">
                                    <v-col cols="7">
                                        <v-card>
                                            <v-checkbox hide-details dense v-model="selectedPin.pin.active"
                                                label="Pin active" @change="updatePin(selectedPin)"></v-checkbox>
                                            <v-alert class="mb-2 pre-wrap" variant="text" color="grey"
                                                icon="mdi-book-open-page-variant">
                                                {{ selectedPin.text }}

                                            </v-alert>
                                            <v-card-actions>
                                                <v-btn v-if="removePinConfirm === false" rounded="sm"
                                                    prepend-icon="mdi-close-box-outline" color="error" variant="text"
                                                    @click.stop="removePinConfirm = true">
                                                    Remove Pin
                                                </v-btn>
                                                <span v-else>
                                                    <v-btn rounded="sm" prepend-icon="mdi-close-box-outline"
                                                        @click.stop="removePin(selectedPin.pin.entry_id)" color="error"
                                                        variant="text">
                                                        Confirm removal
                                                    </v-btn>
                                                    <v-btn class="ml-1" rounded="sm" prepend-icon="mdi-cancel"
                                                        @click.stop="removePinConfirm = false" color="info"
                                                        variant="text">
                                                        Cancel
                                                    </v-btn>
                                                </span>
                                                <v-spacer></v-spacer>
                                                <v-btn variant="text" color="primary"
                                                    @click.stop="loadContextDBEntry(selectedPin.pin.entry_id)"
                                                    prepend-icon="mdi-book-open-page-variant">View in context DB</v-btn>
                                            </v-card-actions>
                                        </v-card>
                                    </v-col>
                                    <v-col cols="5">
                                        <v-card>
                                            <v-card-title><v-icon size="small">mdi-robot</v-icon> Conditional auto
                                                pinning</v-card-title>
                                            <v-card-text>
                                                <v-textarea rows="1" auto-grow v-model="selectedPin.pin.condition"
                                                    label="Condition question prompt for auto pinning"
                                                    hint="The condition that must be met for the pin to be active. Prompt will be evaluated by the AI (World State agent) regularly. This should be a question that the AI can answer with a yes or no."
                                                    @update:model-value="queueUpdatePin(selectedPin)">
                                                </v-textarea>
                                                <v-checkbox hide-details dense v-model="selectedPin.pin.condition_state"
                                                    label="Current condition evaluation"
                                                    @change="updatePin(selectedPin)"></v-checkbox>
                                            </v-card-text>
                                        </v-card>
                                    </v-col>


                                </v-row>
                                <v-alert v-else type="info" color="grey" variant="text" icon="mdi-pin">
                                    Pins allow you to permanently pin a context entry to the AI context. While a pin is
                                    active, the AI will always consider the pinned entry when generating text. <v-icon
                                        color="warning">mdi-alert</v-icon> Pinning too many entries may use up your
                                    available context size, so use them wisely.

                                    <br><br>
                                    Additionally you may also define auto pin conditions that the World State agent will
                                    check every turn. If the condition is met, the entry will be pinned. If the
                                    condition
                                    is no longer met, the entry will be unpinned.

                                    <br><br>
                                    Finally, remember there is also automatic insertion of context based on relevance to
                                    the current scene progress, which happens regardless of pins. Pins are just a way to
                                    ensure that a specific entry is always considered relevant.

                                    <br><br>
                                    <v-btn color="primary" variant="text" prepend-icon="mdi-plus"
                                        @click.stop="tab = 'contextdb'">Add new pins through the context
                                        manager.</v-btn>

                                </v-alert>

                            </v-col>
                        </v-row>
                    </v-card-text>
                </v-card>
            </v-window-item>

            <!-- TEMPLATES -->
            <v-window-item value="templates">
                <WorldStateManagerTemplates ref="templates" />
            </v-window-item>

        </v-window>
        <v-card-actions>
            <v-spacer></v-spacer>
            <!-- Placeholder for any actions -->
        </v-card-actions>
    </v-card>
</template>

<script>
import WorldStateManagerTemplates from './WorldStateManagerTemplates.vue';
import WorldStateManagerWorld from './WorldStateManagerWorld.vue';
import WorldStateManagerCharacter from './WorldStateManagerCharacter.vue';

export default {
    name: 'WorldStateManager',
    components: {
        WorldStateManagerTemplates,
        WorldStateManagerWorld,
        WorldStateManagerCharacter,
    },
    computed: {
        characterStateReinforcementsList() {
            let list = [];
            for (let reinforcement in this.characterDetails.reinforcements) {
                list.push(this.characterDetails.reinforcements[reinforcement]);
            }
            return list;
        },
    },
    data() {
        return {
            // general
            tab: 'characters',
            dialog: false,
            requireSceneSave: false,
            isBusy: false,
            historyEnabled: false,
            insertionModes: [
                { "title": "Passive", "value": "never", "props": { "subtitle": "Rely on pins and relevancy attachment" } },
                { "title": "Sequential", "value": "sequential", "props": { "subtitle": "Insert into current scene progression" } },
                { "title": "Conversation Context", "value": "conversation-context", "props": { "subtitle": "Insert into conversation context for this character" } },
                { "title": "All context", "value": "all-context", "props": { "subtitle": "Insert into all context" } },
            ],
            deferedNavigation: null,
            templates: {
                state_reinforcement: {},
            },

            // characters
            selectedCharacter: null,
            selectedCharacterPage: 'details',
            selectedCharacterDetail: null,
            selectedCharacterStateReinforcer: null,

            contextDBEntryUpdateTimeout: null,

            characterDetailReinforceInterval: 10,
            characterDetailReinforceIntructions: "",

            characterStateTemplateBusy: false,
            showCharacterStateTemplates: false,

            characterList: {
                characters: [],
            },
            characterDetails: {},

            // world

            worldContext: {},

            // history

            // context db

            contextDBQuery: null,
            contextDBQueryMetaKey: null,
            contextDBQueryMetaValue: null,
            contextDBCurrentQuery: null,
            contextDB: { entries: [] },
            contextDBMetaKeys: [
                "character",
                "typ",
                "ts",
                "detail",
                "item",
            ],
            contextDBMetaValuesByType: {
                character: () => {
                    let list = Object.keys(this.characterList.characters);
                    list.push("__narrator__");
                    return list;
                },
                typ: () => {
                    return ["base_attribute", "details", "history", "world_state", "lore"]
                },
            },

            selectedContextDBEntry: null,
            dialogAddContextDBEntry: false,

            newContextDBEntryText: null,
            newContextDBEntryMetaKey: null,
            newContextDBEntryMetaValue: null,
            newContextDBEntryMeta: {},

            // pins

            pins: {},
            selectedPin: null,
            pinUpdateTimeout: null,
            removePinConfirm: false,


        }
    },
    watch: {
        dialog(val) {
            if (val === false) {
                this.saveOnExit();
            }
        },
        tab(val) {
            if (val === 'templates') {
                this.$nextTick(() => {
                    this.$refs.templates.requestTemplates();
                });
            }
        },
        characterDetails() {
            if (this.deferedNavigation !== null) {
                const deferedNavigation = {...this.deferedNavigation}
                console.log("DEFERED", deferedNavigation)
                if (deferedNavigation[0] === 'characters') {

                    this.$refs.characters.selected = deferedNavigation[1];
                    this.$refs.characters.page = deferedNavigation[2];

                    this.$nextTick(() => {
                        if (deferedNavigation[2] == 'attributes') {
                            this.$refs.characters.$refs.attributes.selected = deferedNavigation[3];
                        }
                        else if (deferedNavigation[2] == 'details') {
                            this.$refs.characters.$refs.details.selected = deferedNavigation[3];
                        }
                        else if (deferedNavigation[2] == 'reinforce') {
                            this.$refs.characters.$refs.reinforcements.selected = deferedNavigation[3];
                        }
                    });

                }
                this.deferedNavigation = null;
            }
        }
    },
    provide() {
        return {
            insertionModes: this.insertionModes,
            pins: this.pins,
            addPin: this.addPin,
            entryHasPin: this.entryHasPin,
            selectPin: this.selectPin,
            loadContextDBEntry: this.loadContextDBEntry,
            requestTemplates: this.requestTemplates,
        }
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'setWaitingForInput',
        'openCharacterSheet',
        'characterSheet',
        'isInputDisabled',
        'autocompleteRequest',
        'autocompleteInfoMessage',
    ],
    methods: {
        show(tab, sub1, sub2, sub3) {
            //this.reset();
            this.requestCharacterList();
            this.requestPins();
            this.requestTemplates();

            this.dialog = true;
            if (tab) {
                this.tab = tab;
            }
            if (tab == 'characters') {
                if (sub1 != null) {
                    this.$nextTick(() => {
                        this.loadCharacter(sub1);
                        this.deferedNavigation = ['characters', sub1, sub2, sub3];
                    });
                }
            }
            else if (tab == 'pins') {
                if (sub1 != null) {
                    this.selectedPin = this.pins[sub1];
                }
            }
            else if (tab == 'world') {
                if (sub1 != null) {
                    this.$nextTick(() => {
                        this.$refs.world.navigate(sub1, sub2, sub3);
                    });
                }
            }
        },
        reset() {
            this.characterList = {
                characters: [],
            };
            this.characterDetails = {};
            this.pins = {};
            this.contextDB = { entries: [] };
            this.selectedCharacter = null;
            this.deferSelectedCharacter = null;
            this.selectedCharacterPage = 'details';
            this.selectedCharacterDetail = null;
            this.selectedCharacterStateReinforcer = null;
            this.selectedContextDBEntry = null;
            this.newCharacterDetailName = null;
            this.newCharacterDetailValue = null;
            this.removeCharacterDetailConfirm = false;
            this.resetCharacterStateReinforcerConfirm = false;
            this.characterDetailSearch = null;
            this.newCharacterStateReinforcerInterval = 10;
            this.newCharacterStateReinforcerInstructions = "";
            this.newCharacterStateReinforcerQuestion = null;
            this.newCharacterStateReinforcerInsert = "sequential";
            this.characterDetailDirty = false;
            this.characterStateReinforcerDirty = false;
            this.characterStateTemplateBusy = false;
            this.showCharacterStateTemplates = false;
            this.contextDBCurrentQuery = null;
            this.contextDBQuery = null;
            this.contextDBQueryMetaKey = null;
            this.contextDBQueryMetaValue = null;
            this.newContextDBEntryMeta = {};
            this.newContextDBEntryText = null;
            this.newContextDBEntryMetaKey = null;
            this.newContextDBEntryMetaValue = null;
            this.dialogAddContextDBEntry = false;
            this.selectedPin = null;
            this.pinUpdateTimeout = null;
            this.removePinConfirm = false;
            this.deferedNavigation = null;
            this.isBusy = false;
            this.characterDetailBusy = false;
        },
        exit() {
            this.dialog = false;
        },
        saveOnExit() {
            if (!this.requireSceneSave) {
                return;
            }
            //this.getWebsocket().send(JSON.stringify({ type: 'interact', text: "!save" }));
        },

        // characters

        requestCharacterList() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_list',
            }));
        },

        requestCharacter(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_details',
                name: name,
            }));
        },

        loadCharacter(name) {
            this.requestCharacter(name);
            this.selectedCharacterPage = 'description';
            this.selectedCharacter = name;
        },

        // Character state reinforcement


        // contextdb
        isHiddenMetaTag(name) {
            return name === "session"
        },

        visibleMetaTags(meta) {
            let tags = {}
            for (let name in meta) {
                if (!this.isHiddenMetaTag(name)) {
                    tags[name] = meta[name];
                }
            }
            return tags;
        },

        queryContextDB() {
            let meta = {};

            if (!this.contextDBQuery) {
                return;
            }

            if (this.contextDBQueryMetaKey !== null && this.contextDBQueryMetaValue !== null) {
                meta[this.contextDBQueryMetaKey] = this.contextDBQueryMetaValue;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'query_context_db',
                query: this.contextDBQuery || "",
                meta: meta
            }));
        },

        loadContextDBEntry(id) {
            this.contextDBQuery = "id:" + id;
            this.queryContextDB();
            this.tab = 'contextdb';
        },

        handleNewContextDBEntryMeta() {
            if (this.newContextDBEntryMetaKey === null || this.newContextDBEntryMetaValue === null) {
                return;
            }
            this.newContextDBEntryMeta[this.newContextDBEntryMetaKey] = this.newContextDBEntryMetaValue;
            this.newContextDBEntryMetaKey = null;
            this.newContextDBEntryMetaValue = null;
        },

        handleRemoveContextDBEntryMeta(name) {
            delete this.newContextDBEntryMeta[name];
        },

        queueUpdateContextDBEntry(entry) {
            if (this.contextDBEntryUpdateTimeout !== null) {
                clearTimeout(this.contextDBEntryUpdateTimeout);
            }

            entry.dirty = true;

            this.contextDBEntryUpdateTimeout = setTimeout(() => {
                this.updateContextDBEntry(entry);
                entry.dirty = false;
            }, 500);
        },

        updateContextDBEntry(entry) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_context_db',
                id: entry.id,
                text: entry.text,
                meta: entry.meta,
            }));
        },

        addContextDBEntry() {
            let meta = {};
            for (let key in this.newContextDBEntryMeta) {
                meta[key] = this.newContextDBEntryMeta[key];
            }

            meta.source = "manual";

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_context_db',
                text: this.newContextDBEntryText,
                meta: meta,
            }));
            this.newContextDBEntryText = null;
            this.newContextDBEntryMeta = {};
            this.dialogAddContextDBEntry = false;
        },

        deleteContextDBEntry(id) {
            let confirm = window.confirm("Are you sure you want to delete this entry?");
            if (!confirm) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_context_db',
                id: id,
            }));
        },

        resetContextDB() {
            let confirm = window.confirm("Are you sure you want to reset the context database? This will remove all entries and reimport them from the current save file. Manually added context entries will be lost.");
            if (!confirm) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: "!ltm_reset",
            }));
        },

        // pins

        requestPins() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_pins',
            }));
        },

        pinsExist() {
            return Object.keys(this.pins).length > 0;
        },

        entryHasPin(entryId) {
            return this.pins[entryId] !== undefined;
        },

        entryIsPinned(entryId) {
            return this.entryHasPin(entryId) && this.pins[entryId].pin.active;
        },

        selectPin(entryId) {
            this.selectedPin = this.pins[entryId];
            this.tab = 'pins';
        },

        addPin(entryId) {

            this.pins[entryId] = {
                text: "",
                pin: {
                    entry_id: entryId,
                    active: false,
                    condition: "",
                    condition_state: false,
                }
            };
            this.selectPin(entryId);

            this.updatePin(this.pins[entryId]);
        },

        removePin(entryId) {
            delete this.pins[entryId];
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'remove_pin',
                entry_id: entryId,
            }));
            this.selectedPin = null;
            this.removePinConfirm = false;
        },

        updatePin(pin) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_pin',
                entry_id: pin.pin.entry_id,
                active: pin.pin.active,
                condition: pin.pin.condition,
                condition_state: pin.pin.condition_state,
            }));
        },

        queueUpdatePin(pin) {
            if (this.pinUpdateTimeout !== null) {
                clearTimeout(this.pinUpdateTimeout);
            }

            this.pinUpdateTimeout = setTimeout(() => {
                this.updatePin(pin);
            }, 500);
        },

        // websocket

        requestTemplates: function () {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_templates',
            }));
        },

        handleMessage(message) {



            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'character_list') {
                this.characterList = message.data;
            }
            else if (message.action === 'character_details') {

                // if we are currently editing a state reinforcement, override it in the incoming data
                // this fixes the annoying rubberbanding when editing a state reinforcement
                if (this.characterStateReinforcerDirty) {
                    message.data.reinforcements[this.selectedCharacterStateReinforcer] = this.characterDetails.reinforcements[this.selectedCharacterStateReinforcer];
                }

                this.characterDetails = message.data;


                // select first detail
                if (!this.selectedCharacterDetail)
                    this.selectedCharacterDetail = Object.keys(this.characterDetails.details)[0];

                // loop through characterDetails.base_attributes and characterDetails.details and convert any objects to strings
                for (let attribute in this.characterDetails.base_attributes) {
                    if (typeof this.characterDetails.base_attributes[attribute] === 'object') {
                        this.characterDetails.base_attributes[attribute] = JSON.stringify(this.characterDetails.base_attributes[attribute]);
                    }
                }
            }
            else if (message.action === 'pins') {
                this.pins = message.data.pins;
                if (this.selectedPin != null)
                    this.selectedPin = this.pins[this.selectedPin.pin.entry_id];
                this.requireSceneSave = true;
            }


            else if (message.action === 'context_db_result') {
                this.contextDB = message.data;
                this.contextDBCurrentQuery = this.contextDBQuery;
            }
            else if (message.action === 'context_db_updated') {
                this.requestPins();
                if (this.selectedCharacter)
                    this.requestCharacter(this.selectedCharacter);
                this.$refs.world.requestWorld();
            }
            else if (message.action === 'context_db_deleted') {
                let entry_id = message.data.id;
                for (let i = 0; i < this.contextDB.entries.length; i++) {
                    if (this.contextDB.entries[i].id === entry_id) {
                        this.contextDB.entries.splice(i, 1);
                        break;
                    }
                }
            }
            else if (message.action == 'templates') {
                this.templates = message.data;
            }
            else if (message.action === 'operation_done') {
                this.isBusy = false;
            }

        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmouted() {
        this.saveOnExit();
    }
}
</script>

<style scoped>.inactive {
    opacity: 0.5;
}

.pre-wrap {
    white-space: pre-wrap;
}</style>

<template>
    <v-dialog v-model="dialog" scrollable max-width="1400px" min-height="600px">
        <v-overlay contained v-model="isBusy"></v-overlay>
        <v-card>
            <v-card-title><v-icon class="mr-1">mdi-earth</v-icon>World State Manager
                <v-progress-circular v-if="isBusy" indeterminate color="primary" size="11"></v-progress-circular>
            </v-card-title>
            <v-tabs color="primary" v-model="tab">
                <v-tab value="characters">
                    <v-icon start>mdi-account-group</v-icon>
                    Characters
                </v-tab>
                <v-tab value="history" disabled>
                    <v-icon start>mdi-history</v-icon>
                    History
                </v-tab>
                <v-tab value="contextdb">
                    <v-icon start>mdi-book-open-page-variant</v-icon>
                    Context
                </v-tab>
            </v-tabs>
            <v-window v-model="tab">

                <!-- CHARACTERS -->

                <v-window-item value="characters">
                    <v-card flat>
                        <v-card-text>
                            <v-row>
                                <v-col cols="3">
                                    <v-list>
                                        <v-list-item v-for="character in characterList.characters" :key="character.name" @click="loadCharacter(character.name)">
                                                <v-list-item-title class="text-caption">{{ character.name }}</v-list-item-title>
                                                <v-list-item-subtitle>
                                                    <v-chip v-if="character.is_player === true" label size="x-small" variant="outlined" class="ml-1">Player</v-chip>
                                                    <v-chip v-if="character.is_player === false" label size="x-small" variant="outlined" class="ml-1">AI</v-chip>
                                                    <v-chip v-if="character.active === true && character.is_player === false" label size="x-small" variant="outlined" color="success" class="ml-1">Active</v-chip>
                                                </v-list-item-subtitle>
                                                <v-divider class="mt-2"></v-divider>
                                        </v-list-item>
                                    </v-list>
                                </v-col>
                                <v-col cols="9">
                                    <div v-if="selectedCharacter !== null">
                                        <v-toolbar density="compact">
                                            <v-toolbar-title>
                                                <v-icon size="small">mdi-account</v-icon>
                                                {{ characterDetails.name }}
                                                <v-chip size="x-small" v-if="characterDetails.is_player === false">AI</v-chip>
                                            </v-toolbar-title>
                                            <v-spacer></v-spacer>
                                            <v-btn rounded="sm" prepend-icon="mdi-text-account" @click.stop="selectedCharacterPage='description'">
                                                Description
                                            </v-btn>
                                            <v-btn rounded="sm" prepend-icon="mdi-format-list-bulleted-type" @click.stop="selectedCharacterPage='attributes'">
                                                Attributes
                                            </v-btn>
                                            <v-btn rounded="sm" prepend-icon="mdi-format-list-text" @click.stop="selectedCharacterPage='details'">
                                                Details
                                            </v-btn>
                                            <v-btn rounded="sm" prepend-icon="mdi-image-auto-adjust" @click.stop="selectedCharacterPage='reinforce'">
                                                States
                                            </v-btn>
                                        </v-toolbar>

                                        <!-- CHARACTER DESCRIPTION -->

                                        <div v-if="selectedCharacterPage === 'description'">
                                            <v-textarea
                                                rows="5"
                                                auto-grow
                                                v-model="characterDetails.description"
                                                :color="characterDescriptionDirty ? 'info' : ''"
                                                @update:model-value="queueUpdateCharacterDescription"
                                                label="Description"
                                                hint="A short description of the character."
                                            ></v-textarea>
                                        </div>

                                        <!-- CHARACTER ATTRIBUTES -->

                                        <div v-else-if="selectedCharacterPage === 'attributes'">
                                            <v-toolbar floating density="compact" class="mb-2">
                                                <v-text-field v-model="characterAttributeSearch" label="Filter attributes" append-inner-icon="mdi-magnify" clearable single-line hide-details density="compact" variant="underlined" class="ml-1 mb-1" @update:modelValue="autoSelectFilteredAttribute"></v-text-field>
                                                <v-spacer></v-spacer>
                                                <v-text-field v-model="newCharacterAttributeName" label="New attribute" append-inner-icon="mdi-plus" class="mr-1 mb-1" variant="underlined"  single-line hide-details density="compact" @keyup.enter="handleNewCharacterAttribute"></v-text-field>
                                            </v-toolbar>
                                            <v-row>
                                                <v-col cols="4">
                                                    <v-list>
                                                        <v-list-item v-for="(value, attribute) in filteredCharacterAttributes()" :key="attribute" @click="selectedCharacterAttribute=attribute">
                                                            <v-list-item-title class="text-caption">{{ attribute }}</v-list-item-title>
                                                        </v-list-item>
                                                    </v-list>  
                                                </v-col>
                                                <v-col cols="8">
                                                    <div v-if="selectedCharacterAttribute !== null">
                                                        <v-textarea
                                                            ref="characterAttribute"
                                                            rows="5"
                                                            auto-grow
                                                            :label="selectedCharacterAttribute"
                                                            :color="characterAttributeDirty ? 'info' : ''"
                                                            @update:modelValue="queueUpdateCharacterAttribute(selectedCharacterAttribute)"
                                                            v-model="characterDetails.base_attributes[selectedCharacterAttribute]">
                                                        </v-textarea>
                                                    </div>
                                                    <v-row v-if="selectedCharacterAttribute !== null">
                                                        <v-col cols="12">
                                                            <v-btn v-if="removeCharacterAttributeConfirm===false" rounded="sm" prepend-icon="mdi-delete" color="error" variant="text" @click.stop="removeCharacterAttributeConfirm=true" >
                                                                Remove attribute
                                                            </v-btn>
                                                            <div v-else>
                                                                <v-btn rounded="sm" prepend-icon="mdi-delete" @click.stop="deleteCharacterAttribute(selectedCharacterAttribute)"  color="error" variant="text">
                                                                    Confirm removal
                                                                </v-btn>
                                                                <v-btn class="ml-1" rounded="sm" prepend-icon="mdi-cancel" @click.stop="removeCharacterAttributeConfirm=false" color="info" variant="text">
                                                                    Cancel
                                                                </v-btn>
                                                            </div>

                                                        </v-col>
                                                    </v-row>
                                                </v-col>
                                            </v-row>
                                        </div>

                                        <!-- CHARACTER DETAILS -->

                                        <div v-else-if="selectedCharacterPage === 'details'">
                                            <v-toolbar floating density="compact" class="mb-2">
                                                <v-text-field v-model="characterDetailSearch" label="Filter details" append-inner-icon="mdi-magnify" clearable single-line hide-details density="compact" variant="underlined" class="ml-1 mb-1" @update:modelValue="autoSelectFilteredDetail"></v-text-field>
                                                <v-spacer></v-spacer>
                                                <v-text-field v-model="newCharacterDetailName" label="New detail" append-inner-icon="mdi-plus" class="mr-1 mb-1" variant="underlined"  single-line hide-details density="compact" @keyup.enter="handleNewCharacterDetail"></v-text-field>
                                            </v-toolbar>
                                            <v-row>
                                                <v-col cols="4">
                                                    <v-list>
                                                        <v-list-item v-for="(value, detail) in filteredCharacterDetails()" :key="detail" @click="selectedCharacterDetail=detail">
                                                            <v-list-item-title class="text-caption">{{ detail }}</v-list-item-title>
                                                        </v-list-item>
                                                    </v-list>  
                                                </v-col>
                                                <v-col cols="8">
                                                    <div v-if="selectedCharacterDetail">
                                                        <v-textarea
                                                            rows="5"
                                                            max-rows="10"
                                                            auto-grow
                                                            ref="characterDetail"
                                                            :color="characterDetailDirty ? 'info' : ''"
                                                            @update:modelValue="queueUpdateCharacterDetail(selectedCharacterDetail)"
                                                            :label="selectedCharacterDetail"
                                                            v-model="characterDetails.details[selectedCharacterDetail]">
                                                        </v-textarea>


                                                    </div>

                                                    <v-row v-if="selectedCharacterDetail">
                                                        <v-col cols="6">
                                                            <v-btn v-if="removeCharacterDetailConfirm===false" rounded="sm" prepend-icon="mdi-delete" color="error" variant="text" @click.stop="removeCharacterDetailConfirm=true" >
                                                                Remove detail
                                                            </v-btn>
                                                            <div v-else>
                                                                <v-btn rounded="sm" prepend-icon="mdi-delete" @click.stop="deleteCharacterDetail(selectedCharacterDetail)"  color="error" variant="text">
                                                                    Confirm removal
                                                                </v-btn>
                                                                <v-btn class="ml-1" rounded="sm" prepend-icon="mdi-cancel" @click.stop="removeCharacterDetailConfirm=false" color="info" variant="text">
                                                                    Cancel
                                                                </v-btn>
                                                            </div>

                                                        </v-col>
                                                        <v-col cols="6">
                                                            <div v-if="characterDetails.reinforcements[selectedCharacterDetail]">
                                                                <v-btn rounded="sm" prepend-icon="mdi-image-auto-adjust" @click.stop="viewCharacterStateReinforcer(selectedCharacterDetail)" color="primary" variant="text">
                                                                    Manage auto state
                                                                </v-btn>
                                                            </div>
                                                            <div v-else>
                                                                <v-btn rounded="sm" prepend-icon="mdi-image-auto-adjust" @click.stop="viewCharacterStateReinforcer(selectedCharacterDetail)" color="primary" variant="text">
                                                                    Setup auto state
                                                                </v-btn>
                                                            </div>
                                                        </v-col>
                                                    </v-row>

                                                </v-col>
                                            </v-row>
                                        </div>

                                        <!-- CHARACTER STATE REINFORCERS -->

                                        <div v-else-if="selectedCharacterPage === 'reinforce'">
                                            <v-toolbar floating density="compact" class="mb-2">
                                                <v-text-field v-model="characterStateReinforcerSearch" label="Filter states" append-inner-icon="mdi-magnify" clearable single-line hide-details density="compact" variant="underlined" class="ml-1 mb-1" @update:modelValue="autoSelectFilteredStateReinforcer"></v-text-field>
                                                <v-spacer></v-spacer>
                                                <v-text-field v-model="newCharacterStateReinforcerQuestion" label="New state" append-inner-icon="mdi-plus" class="mr-1 mb-1" variant="underlined"  single-line hide-details density="compact" @keyup.enter="handleNewCharacterStateReinforcer"></v-text-field>
                                            </v-toolbar>
                                            <v-row>
                                                <v-col cols="4">
                                                    <v-list>
                                                        <v-list-item v-for="(value, detail) in filteredCharacterStateReinforcers()" :key="detail" @click="selectedCharacterStateReinforcer=detail">
                                                            <v-list-item-title class="text-caption">{{ detail }}</v-list-item-title>
                                                            <v-list-item-subtitle>
                                                                <v-chip size="x-small">update in {{ value.due }} turns</v-chip>
                                                            </v-list-item-subtitle>
                                                        </v-list-item>
                                                    </v-list>  
                                                </v-col>
                                                <v-col cols="8">
                                                    <div v-if="selectedCharacterStateReinforcer">
                                                        <v-textarea rows="3" auto-grow max-rows="5" :label="selectedCharacterStateReinforcer" v-model="characterDetails.reinforcements[selectedCharacterStateReinforcer].answer"  @update:modelValue="queueUpdateCharacterStateReinforcement(selectedCharacterStateReinforcer)" :color="characterStateReinforcerDirty ? 'info' : ''"></v-textarea>
                                                        <v-text-field v-model="characterDetails.reinforcements[selectedCharacterStateReinforcer].interval" label="Re-inforce / Update detail every N turns" type="number" min="1" max="100" step="1" class="mb-2" @update:modelValue="queueUpdateCharacterStateReinforcement(selectedCharacterStateReinforcer)" :color="characterStateReinforcerDirty ? 'info' : ''"></v-text-field>
                                                        <v-textarea rows="3" auto-grow max-rows="5" label="Additional instructions to the AI for generating this state." v-model="characterDetails.reinforcements[selectedCharacterStateReinforcer].instructions" @update:modelValue="queueUpdateCharacterStateReinforcement(selectedCharacterStateReinforcer)" :color="characterStateReinforcerDirty ? 'info' : ''"></v-textarea>
                                                        
                                                        <v-row>
                                                            <v-col cols="6">
                                                                <div v-if="removeCharacterStateReinforcerConfirm===false">
                                                                    <v-btn rounded="sm" prepend-icon="mdi-delete" color="error" variant="text" @click.stop="removeCharacterStateReinforcerConfirm=true" >
                                                                        Remove state
                                                                    </v-btn>
                                                                </div>
                                                                <div v-else>
                                                                    <v-btn rounded="sm" prepend-icon="mdi-delete" @click.stop="deleteCharacterStateReinforcement(selectedCharacterStateReinforcer)"  color="error" variant="text">
                                                                        Confirm removal
                                                                    </v-btn>
                                                                    <v-btn class="ml-1" rounded="sm" prepend-icon="mdi-cancel" @click.stop="removeCharacterStateReinforcerConfirm=false" color="info" variant="text">
                                                                        Cancel
                                                                    </v-btn>
                                                                </div>
                                                            </v-col>
                                                            <v-col cols="6">
                                                                <v-btn rounded="sm" prepend-icon="mdi-refresh" @click.stop="runCharacterStateReinforcement(selectedCharacterStateReinforcer)" color="primary" variant="text">
                                                                    Refresh State
                                                                </v-btn>
                                                            </v-col>
                                                        </v-row>
                                                    </div>
                                                </v-col>
                                            </v-row>
                                        </div>
                                    </div>
                                </v-col>
                            </v-row>
                        </v-card-text>
                    </v-card>
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
                            <v-toolbar floating density="compact" class="mb-2">
                                <v-text-field v-model="contextDBQuery" label="Content search" append-inner-icon="mdi-magnify" clearable single-line hide-details density="compact" variant="underlined" class="ml-1 mb-1 mr-1" @keyup.enter="queryContextDB"></v-text-field>

                                <v-select v-model="contextDBQueryMetaKey" :items="contextDBMetaKeys" label="Filter By Tag" class="mr-1 mb-1" variant="underlined"  single-line hide-details density="compact"></v-select>
                                <v-select v-if="contextDBQueryMetaKey !== null && contextDBMetaValuesByType[contextDBQueryMetaKey]" v-model="contextDBQueryMetaValue" :items="contextDBMetaValuesByType[contextDBQueryMetaKey]()" label="Tag value"  class="mr-1 mb-1" variant="underlined"  single-line hide-details density="compact"></v-select>
                                <v-text-field v-else v-model="contextDBQueryMetaValue" label="Tag value"  class="mr-1 mb-1" variant="underlined"  single-line hide-details density="compact"></v-text-field>
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
                                <v-btn rounded="sm" prepend-icon="mdi-plus" @click.stop="dialogAddContextDBEntry=true"  variant="text">
                                    Add entry
                                </v-btn>
                            </v-toolbar>

                            <!-- add entry-->
                            <v-card v-if="dialogAddContextDBEntry === true">
                                <v-card-title>
                                    Add entry
                                </v-card-title>
                                <v-card-text>
                                    <v-row>
                                        <v-col cols="12">
                                            <v-textarea
                                                rows="5"
                                                auto-grow
                                                v-model="newContextDBEntryText"
                                                label="Content"
                                                hint="The content of the entry."
                                            ></v-textarea>
                                        </v-col>
                                    </v-row>
                                    <v-row>
                                        <v-col cols="12">
                                            <v-chip v-for="(value, name) in newContextDBEntryMeta" :key="name" label size="x-small" variant="outlined" class="ml-1" closable @click:close="handleRemoveContextDBEntryMeta(name)">{{ name }}: {{ value }}</v-chip>
                                        </v-col>
                                    </v-row>
                                    <v-row>
                                        <v-col cols="3">
                                            <v-select v-model="newContextDBEntryMetaKey" :items="contextDBMetaKeys" label="Meta key" class="mr-1 mb-1" variant="underlined"  single-line hide-details density="compact"></v-select>
                                        </v-col>
                                        <v-col cols="3">
                                            <v-select v-if="newContextDBEntryMetaKey !== null && contextDBMetaValuesByType[newContextDBEntryMetaKey]" v-model="newContextDBEntryMetaValue" :items="contextDBMetaValuesByType[newContextDBEntryMetaKey]()" label="Meta value"  class="mr-1 mb-1" variant="underlined"  single-line hide-details density="compact"></v-select>
                                            <v-text-field v-else v-model="newContextDBEntryMetaValue" label="Meta value"  class="mr-1 mb-1" variant="underlined"  single-line hide-details density="compact"></v-text-field>
                                        </v-col>
                                        <v-col cols="3">
                                            <v-btn rounded="sm" color="primary" prepend-icon="mdi-plus" @click.stop="handleNewContextDBEntryMeta"  variant="text">
                                                Add meta
                                            </v-btn>
                                        </v-col>
                                    </v-row>
                                </v-card-text>
                                <v-card-actions>
                                    <!-- cancel -->
                                    <v-btn rounded="sm" prepend-icon="mdi-cancel" @click.stop="dialogAddContextDBEntry=false" color="info" variant="text">
                                        Cancel
                                    </v-btn>
                                    <v-spacer></v-spacer>
                                    <!-- add -->
                                    <v-btn rounded="sm" prepend-icon="mdi-plus" @click.stop="addContextDBEntry" color="primary" variant="text">
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
                                            <th class="text-left">Tags</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr v-for="entry in contextDB.entries" :key="entry.id">
                                            <td>
                                                <!-- remove -->
                                                <v-btn icon size="x-small" rounded="sm" color="red" variant="text" @click.stop="deleteContextDBEntry(entry.id)">
                                                    <v-icon>mdi-delete</v-icon>
                                                </v-btn>
                                            </td>
                                            <td>
                                                <v-textarea
                                                    rows="1"
                                                    auto-grow
                                                    density="compact"
                                                    hide-details
                                                    :color="entry.dirty ? 'info' : ''"
                                                    v-model="entry.text"
                                                    @update:model-value="queueUpdateContextDBEntry(entry)"
                                                ></v-textarea>
                                            </td>
                                            <td>
                                                <!-- render entry.meta as v-chip elements showing both name and value -->
                                                <v-chip v-for="(value, name) in entry.meta" :key="name" label size="x-small" variant="outlined" class="ml-1">{{ name }}: {{ value }}</v-chip>
                                            </td>
                                        </tr>
                                    </tbody>
                                </v-table>
                                <v-alert v-else-if="contextDBCurrentQuery" dense type="warning" variant="text" icon="mdi-information-outline">
                                    No results
                                </v-alert>
                                <v-alert v-else dense type="info" variant="text" icon="mdi-magnify">
                                    Enter a query to search the context database.
                                </v-alert>
                            </div>

                        </v-card-text>
                    </v-card>
                </v-window-item>

            </v-window>
            <v-card-actions>
                <v-spacer></v-spacer>
                <!-- Placeholder for any actions -->
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>

export default {
    name: 'WorldStateManager',
    computed: {
        characterStateReinforcementsList() {
            let list = [];
            for(let reinforcement in this.characterDetails.reinforcements) {
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

            // characters
            selectedCharacter: null,
            selectedCharacterPage: 'description',
            selectedCharacterAttribute: null,
            selectedCharacterDetail: null,
            selectedCharacterStateReinforcer: null,

            newCharacterAttributeName: null,
            newCharacterAttributeValue: null,

            newCharacterDetailName: null,
            newCharacterDetailValue: null,

            newCharacterStateReinforcerInterval: 10,
            newCharacterStateReinforcerInstructions: "",
            newCharacterStateReinforcerQuestion: null,

            removeCharacterAttributeConfirm: false,
            removeCharacterDetailConfirm: false,
            removeCharacterStateReinforcerConfirm: false,

            characterAttributeSearch: null,
            characterDetailSearch: null,
            characterStateReinforcerSearch: null,

            characterAttributeDirty: false,
            characterDetailDirty: false,
            characterDescriptionDirty: false,
            characterStateReinforcerDirty: false,

            characterAttributeUpdateTimeout: null,
            characterDetailUpdateTimeout: null,
            characterDescriptionUpdateTimeout: null,
            contextDBEntryUpdateTimeout: null,

            characterDetailReinforceInterval: 10,
            characterDetailReinforceIntructions: "",

            characterList: {
                characters: [],
            },
            characterDetails: {},

            // history

            // context db

            contextDBQuery: null,
            contextDBQueryMetaKey: null,
            contextDBQueryMetaValue: null,
            contextDBCurrentQuery: null,
            contextDB: {entries: []},
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
        }
    },
    watch: {
        dialog(val) {
            if(val === false) {
                this.saveOnExit();
            }
        },
    },
    inject: [
        'getWebsocket', 
        'registerMessageHandler', 
        'setWaitingForInput',
        'openCharacterSheet',
        'characterSheet',
        'isInputDisabled',
    ],
    methods: {
        show() {
            this.reset();
            this.requestCharacterList();
            this.dialog = true;
        },
        reset() {
            this.characterList = {
                characters: [],
            };
            this.characterDetails = {};
            this.contextDB = {entries: []};
            this.selectedCharacter = null;
            this.selectedCharacterPage = 'description';
            this.selectedCharacterAttribute = null;
            this.selectedCharacterDetail = null;
            this.selectedCharacterStateReinforcer = null;
            this.selectedContextDBEntry = null;
            this.newCharacterAttributeName = null;
            this.newCharacterAttributeValue = null;
            this.newCharacterDetailName = null;
            this.newCharacterDetailValue = null;
            this.removeCharacterAttributeConfirm = false;
            this.removeCharacterDetailConfirm = false;
            this.characterAttributeSearch = null;
            this.characterDetailSearch = null;
            this.newCharacterStateReinforcerInterval = 10;
            this.newCharacterStateReinforcerInstructions = "";
            this.newCharacterStateReinforcerQuestion = null;
            this.characterAttributeDirty = false;
            this.characterDetailDirty = false;
            this.characterDescriptionDirty = false;
            this.characterStateReinforcerDirty = false;
            this.contextDBCurrentQuery = null;
            this.contextDBQuery = null;
            this.contextDBQueryMetaKey = null;
            this.contextDBQueryMetaValue = null;
            this.newContextDBEntryMeta = {};
            this.newContextDBEntryText = null;
            this.newContextDBEntryMetaKey = null;
            this.newContextDBEntryMetaValue = null;
            this.dialogAddContextDBEntry = false;
            this.isBusy = false;
        },
        exit() {
            this.dialog = false;
        },
        saveOnExit() {
            if(!this.requireSceneSave) {
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

        loadCharacter(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_details',
                name: name,
            }));
            this.selectedCharacterPage = 'description';
            this.selectedCharacter = name;
        },

        // character attributes

        filteredCharacterAttributes() {
            if(this.characterAttributeSearch === null) {
                return this.characterDetails.base_attributes;
            }

            let filtered = {};
            for(let attribute in this.characterDetails.base_attributes) {
                if(attribute.toLowerCase().includes(this.characterAttributeSearch.toLowerCase())) {
                    filtered[attribute] = this.characterDetails.base_attributes[attribute];
                }
            }
            return filtered;
        },

        autoSelectFilteredAttribute() {
            // if there is only one attribute in the filtered list, select it
            if(Object.keys(this.filteredCharacterAttributes()).length === 1) {
                this.selectedCharacterAttribute = Object.keys(this.filteredCharacterAttributes())[0];
            }
        },

        queueUpdateCharacterAttribute(name) {
            if(this.characterAttributeUpdateTimeout !== null) {
                clearTimeout(this.characterAttributeUpdateTimeout);
            }

            this.characterAttributeDirty = true;

            this.characterAttributeUpdateTimeout = setTimeout(() => {
                this.updateCharacterAttribute(name);
            }, 500);
        },

        updateCharacterAttribute(name) {
            return this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_attribute',
                name: this.selectedCharacter,
                attribute: name,
                value: this.characterDetails.base_attributes[name],
            }));
        },

        handleNewCharacterAttribute() {
            this.characterDetails.base_attributes[this.newCharacterAttributeName] = "";
            this.selectedCharacterAttribute = this.newCharacterAttributeName;
            this.newCharacterAttributeName = null;
            // set focus to the new attribute
            this.$refs.characterAttribute.focus();
        },

        deleteCharacterAttribute(name) {
            // set value to blank
            this.characterDetails.base_attributes[name] = "";
            this.removeCharacterAttributeConfirm = false;
            // send update
            this.updateCharacterAttribute(name);
            // remove attribute from list
            delete this.characterDetails.base_attributes[name];
            this.selectedCharacterAttribute = null;
        },

        // character details

        filteredCharacterDetails() {
            if(this.characterDetailSearch === null) {
                return this.characterDetails.details;
            }

            let filtered = {};
            for(let detail in this.characterDetails.details) {
                if(detail.toLowerCase().includes(this.characterDetailSearch.toLowerCase())) {
                    filtered[detail] = this.characterDetails.details[detail];
                }
            }
            return filtered;
        },

        autoSelectFilteredDetail() {
            // if there is only one detail in the filtered list, select it
            if(Object.keys(this.filteredCharacterDetails()).length === 1) {
                this.selectedCharacterDetail = Object.keys(this.filteredCharacterDetails())[0];
            }
        },

        queueUpdateCharacterDetail(name) {
            if(this.characterDetailUpdateTimeout !== null) {
                clearTimeout(this.characterDetailUpdateTimeout);
            }

            this.characterDetailDirty = true;

            this.characterDetailUpdateTimeout = setTimeout(() => {
                this.updateCharacterDetail(name);
            }, 500);
        },

        updateCharacterDetail(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_detail',
                name: this.selectedCharacter,
                detail: name,
                value: this.characterDetails.details[name],
            }));
        },

        handleNewCharacterDetail() {
            this.characterDetails.details[this.newCharacterDetailName] = "";
            this.selectedCharacterDetail = this.newCharacterDetailName;
            this.newCharacterDetailName = null;
            // set focus to the new detail
            this.$refs.characterDetail.focus();
        },

        deleteCharacterDetail(name) {
            // set value to blank
            this.characterDetails.details[name] = "";
            this.removeCharacterDetailConfirm = false;
            // send update
            this.updateCharacterDetail(name);
            // remove detail from list
            delete this.characterDetails.details[name];
            this.selectedCharacterDetail = null;
        },

        // Character state reinforcement

        filteredCharacterStateReinforcers() {
            if(this.characterStateReinforcerSearch === null) {
                return this.characterDetails.reinforcements;
            }

            let filtered = {};
            for(let detail in this.characterDetails.reinforcements) {
                if(detail.toLowerCase().includes(this.characterStateReinforcerSearch.toLowerCase())) {
                    filtered[detail] = this.characterDetails.reinforcements[detail];
                }
            }
            return filtered;
        },

        autoSelectFilteredStateReinforcer() {
            // if there is only one detail in the filtered list, select it
            if(Object.keys(this.filteredCharacterStateReinforcers()).length === 1) {
                this.selectedCharacterStateReinforcer = Object.keys(this.filteredCharacterStateReinforcers())[0];
            }
        },

        viewCharacterStateReinforcer(name) {
            if(this.characterDetails.reinforcements[name]) {
                this.selectedCharacterStateReinforcer = name;
            } else {
                this.addCharacterStateReinforcement(name);
                this.updateCharacterStateReinforcement(name, true);
                this.selectedCharacterStateReinforcer = name;
            }
            this.selectedCharacterPage = 'reinforce';
        },

        handleNewCharacterStateReinforcer() {
            this.addCharacterStateReinforcement(this.newCharacterStateReinforcerQuestion);
            this.updateCharacterStateReinforcement(this.newCharacterStateReinforcerQuestion, true);
            this.selectedCharacterStateReinforcer = this.newCharacterStateReinforcerQuestion;
            this.newCharacterStateReinforcerQuestion = null;
        },

        addCharacterStateReinforcement(name) {
            this.characterDetails.reinforcements[name] = {
                interval: this.characterDetailReinforceInterval,
                instructions: this.characterDetailReinforceIntructions,
            };
        },

        queueUpdateCharacterStateReinforcement(name) {
            if(this.characterStateReinforcerUpdateTimeout !== null) {
                clearTimeout(this.characterStateReinforcerUpdateTimeout);
            }

            this.characterStateReinforcerDirty = true;

            this.characterStateReinforcerUpdateTimeout = setTimeout(() => {
                this.updateCharacterStateReinforcement(name);
            }, 500);
        },

        updateCharacterStateReinforcement(name, updateState) {
            let interval = this.characterDetails.reinforcements[name].interval;
            let instructions = this.characterDetails.reinforcements[name].instructions;
            if(updateState === true)
                this.isBusy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_character_detail_reinforcement',
                name: this.selectedCharacter,
                question: name,
                interval: interval,
                instructions: instructions,
                answer: this.characterDetails.reinforcements[name].answer,
                update_state: updateState,
            }));
        },

        deleteCharacterStateReinforcement(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_character_detail_reinforcement',
                name: this.selectedCharacter,
                question: name,
            }));

            if(this.characterDetails.reinforcements[name])
                delete this.characterDetails.reinforcements[name];

            this.removeCharacterStateReinforcerConfirm = false;

            // select first detail
            if(this.selectedCharacterStateReinforcer == name)
                this.selectedCharacterStateReinforcer = Object.keys(this.characterDetails.reinforcements)[0];
        },

        runCharacterStateReinforcement(name) {
            this.isBusy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'run_character_detail_reinforcement',
                name: this.selectedCharacter,
                question: name,
            }));
        },

        // character description

        queueUpdateCharacterDescription() {
            if(this.characterDescriptionUpdateTimeout !== null) {
                clearTimeout(this.characterDescriptionUpdateTimeout);
            }

            this.characterDescriptionDirty = true;

            this.characterDescriptionUpdateTimeout = setTimeout(() => {
                this.updateCharacterDescription();
            }, 500);
        },

        updateCharacterDescription() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_description',
                name: this.selectedCharacter,
                attribute: 'description',
                value: this.characterDetails.description,
            }));
        },

        // contextdb

        queryContextDB() {
            let meta = {};

            if(!this.contextDBQuery) {
                return;
            }

            if(this.contextDBQueryMetaKey !== null && this.contextDBQueryMetaValue !== null) {
                meta[this.contextDBQueryMetaKey] = this.contextDBQueryMetaValue;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'query_context_db',
                query: this.contextDBQuery || "",
                meta: meta
            }));
        },

        handleNewContextDBEntryMeta() {
            if(this.newContextDBEntryMetaKey === null || this.newContextDBEntryMetaValue === null) {
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
            if(this.contextDBEntryUpdateTimeout !== null) {
                clearTimeout(this.contextDBEntryUpdateTimeout);
            }

            entry.dirty = true;

            this.contextDBEntryUpdateTimeout = setTimeout(() => {
                this.updateContextDBEntry(entry);
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
            for(let key in this.newContextDBEntryMeta) {
                meta[key] = this.newContextDBEntryMeta[key];
            }
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
            if(!confirm) {
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
            if(!confirm) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: "!ltm_reset",
            }));
        },

        // websocket

        handleMessage(message) {
            if(message.type !== 'world_state_manager') {
                return;
            }

            if(message.action === 'character_list') {
                this.characterList = message.data;
                console.log(this.characterList);
            }
            else if(message.action === 'character_details') {
                this.characterDetails = message.data;
                // select first attribute
                if(!this.selectedCharacterAttribute)
                    this.selectedCharacterAttribute = Object.keys(this.characterDetails.base_attributes)[0];
                // select first detail
                if(!this.selectedCharacterDetail)
                    this.selectedCharacterDetail = Object.keys(this.characterDetails.details)[0];

                // loop through characterDetails.base_attributes and characterDetails.details and convert any objects to strings
                for(let attribute in this.characterDetails.base_attributes) {
                    if(typeof this.characterDetails.base_attributes[attribute] === 'object') {
                        this.characterDetails.base_attributes[attribute] = JSON.stringify(this.characterDetails.base_attributes[attribute]);
                    }
                }

                console.log("DETAILS", this.characterDetails);
                
            }    
            else if(message.action === 'character_attribute_updated') {
                this.characterAttributeDirty = false;
                this.requireSceneSave = true;
            }
            else if(message.action === 'character_detail_updated') {
                this.characterDetailDirty = false;
                this.requireSceneSave = true;
            }
            else if(message.action === 'character_description_updated') {
                this.characterDescriptionDirty = false;
                this.requireSceneSave = true;
            }
            else if(message.action === 'character_detail_reinforcement_set') {
                this.characterStateReinforcerDirty = false;
                this.requireSceneSave = true;
            }
            else if(message.action === 'character_detail_reinforcement_deleted') {
                this.requireSceneSave = true;
            }
            else if(message.action === 'context_db_result') {
                this.contextDB = message.data;
                this.contextDBCurrentQuery = this.contextDBQuery;
            }
            else if(message.action === 'context_db_deleted') {
                let entry_id = message.data.id;
                for(let i = 0; i < this.contextDB.entries.length; i++) {
                    if(this.contextDB.entries[i].id === entry_id) {
                        this.contextDB.entries.splice(i, 1);
                        break;
                    }
                }
            }
            else if(message.action === 'operation_done') {
                this.isBusy = false;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}
</script>

<style scoped>
/* Placeholder for scoped styles */
</style>

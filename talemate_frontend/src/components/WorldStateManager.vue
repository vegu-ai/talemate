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
                <WorldStateManagerWorld ref="world" 
                @request-sync="onRequestSync"
                @load-pin="onLoadPin"
                @add-pin="onAddPin"
                :pins="pins"
                />
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
                <WorldStateManagerContextDB ref="contextdb"
                @request-sync="onRequestSync"
                @load-pin="onLoadPin"
                @add-pin="onAddPin"
                :pins="pins"
                :character-list="characterList"
                />
            </v-window-item>

            <!-- PINS -->

            <v-window-item value="pins">
                <WorldStateManagerPins 
                :immutable-pins="pins"
                ref="pins" />
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
import WorldStateManagerContextDB from './WorldStateManagerContextDB.vue';
import WorldStateManagerPins from './WorldStateManagerPins.vue';

export default {
    name: 'WorldStateManager',
    components: {
        WorldStateManagerTemplates,
        WorldStateManagerWorld,
        WorldStateManagerCharacter,
        WorldStateManagerContextDB,
        WorldStateManagerPins,
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

            

            characterDetailReinforceInterval: 10,
            characterDetailReinforceIntructions: "",

            characterStateTemplateBusy: false,
            showCharacterStateTemplates: false,

            characterList: {
                characters: [],
            },
            characterDetails: {},
            worldContext: {},
            pins: {},

        }
    },
    emits: [
        'world-state-manager-navigate-r'
    ],
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
            this.$emit('world-state-manager-navigate-r', val)
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
            requestTemplates: this.requestTemplates,
            loadContextDBEntry: this.loadContextDBEntry,
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
            this.deferSelectedCharacter = null;
            this.deferedNavigation = null;
            this.isBusy = false;
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

        onRequestSync() {
            this.requestPins()
        },

        onLoadPin(entryId) {
            this.tab = 'pins';
            this.$nextTick(() => {
                this.$refs.pins.selectPin(entryId)
            });
        },

        onAddPin(entryId) {
            this.tab = 'pins'
            this.$nextTick(() => {
                this.$refs.pins.add(entryId)
            });
        },

        // contextdb

        loadContextDBEntry(entryId) {
            this.tab = 'contextdb';
            this.$nextTick(() => {
                this.$refs.contextdb.load(entryId);
            });
        },

        // pins

        requestPins() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_pins',
            }));
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

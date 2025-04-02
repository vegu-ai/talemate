<template>
    <v-card variant="text">
        <v-tabs v-model="tab" color="secondary">
            <v-tab v-for="tab in tabs" :disabled="tab.disabled" :key="tab.name" :text="tab.title" :prepend-icon="tab.icon" :value="tab.name">
            </v-tab>
        </v-tabs>

        <v-toolbar rounded="md" density="compact" color="grey-darken-4" class="pl-2 mb-1" v-if="tab !== 'templates'">

            <RequestInput ref="requestSaveCopyName" title="Save Scene As" @continue="(name) => { saveScene(name) }" /> 

            <v-menu>
                <template v-slot:activator="{ props }">
                    <v-btn v-bind="props" :disabled="isInputDisabled()" icon :color="scene.saved ? 'muted' : 'secondary'">
                        <v-icon>mdi-content-save</v-icon>
                    </v-btn>
                </template>
                <v-list slim density="compact">
                    <v-list-item @click="saveScene(!scene.data.filename)" prepend-icon="mdi-content-save">
                        <v-list-item-title>Save</v-list-item-title>
                    </v-list-item>
                    <v-list-item @click="saveScene(true)" prepend-icon="mdi-content-save-all">
                        <v-list-item-title>Save Copy ...</v-list-item-title>
                    </v-list-item>
                </v-list>
            </v-menu>

            <span v-if="!scene.saved" class="text-muted text-caption mr-1">Unsaved changes.</span>
            <v-chip v-if="scene && scene.data != null" size="x-small" prepend-icon="mdi-file" label class="text-caption text-muted">{{ scene.data.filename }}</v-chip>
            <v-spacer></v-spacer>
            <GenerationOptions :templates="templates" ref="generationOptions" @change="(opt) => { updateGenerationOptions(opt) }" />
        </v-toolbar>

        <v-window v-model="tab">

            <!-- SCENE -->

            <v-window-item value="scene">
                <WorldStateManagerScene ref="scene" 
                :templates="templates"
                :app-config="appConfig"
                :generation-options="generationOptions"
                :scene="scene ? scene : null" />
            </v-window-item>

            <!-- CHARACTERS -->

            <v-window-item value="characters">
                <WorldStateManagerCharacter 
                ref="characters" 
                @require-scene-save="requireSceneSave = true"
                @selected-character="(character) => { $emit('selected-character', character) }"
                @world-state-manager-navigate="show"
                :generation-options="generationOptions"
                :templates="templates"
                :scene="scene"
                :agent-status="agentStatus"
                :character-list="characterList"
                :app-busy="appBusy" />
            </v-window-item>

            <!-- WORLD -->

            <v-window-item value="world">
                <WorldStateManagerWorld ref="world" 
                @request-sync="onRequestSync"
                @load-pin="onLoadPin"
                @add-pin="onAddPin"
                :generation-options="generationOptions"
                :entries="worldEntries"
                :states="worldStates"
                :pins="pins"
                />
            </v-window-item>

            <!-- HISTORY -->

            <v-window-item value="history">
                <WorldStateManagerHistory ref="history" 
                :scene="scene"
                :generation-options="generationOptions"
                />
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

            <!-- SUGGESTIONS -->
            <v-window-item value="suggestions">
                <WorldStateManagerSuggestions
                ref="suggestions" 
                />
            </v-window-item>

            <!-- TEMPLATES -->
            <v-window-item value="templates">
                <WorldStateManagerTemplates 
                :immutable-templates="worldStateTemplates"
                ref="templates" />
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
import WorldStateManagerScene from './WorldStateManagerScene.vue';
import WorldStateManagerHistory from './WorldStateManagerHistory.vue';
import WorldStateManagerSuggestions from './WorldStateManagerSuggestions.vue';
import GenerationOptions from './GenerationOptions.vue';
import RequestInput from './RequestInput.vue';


export default {
    name: 'WorldStateManager',
    components: {
        WorldStateManagerTemplates,
        WorldStateManagerWorld,
        WorldStateManagerCharacter,
        WorldStateManagerContextDB,
        WorldStateManagerPins,
        WorldStateManagerScene,
        WorldStateManagerHistory,
        WorldStateManagerSuggestions,
        GenerationOptions,
        RequestInput,
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
    props: {
        scene: Object,
        worldStateTemplates: Object,
        agentStatus: Object,
        appConfig: Object,
        appBusy: Boolean,
    },
    data() {
        return {
            // general
            tab: 'scene',
            tabs: [
                {
                    name: "scene",
                    title: "Scene",
                    icon: "mdi-script"
                },
                {
                    name: "characters",
                    title: "Characters",
                    icon: "mdi-account-group"
                },
                {
                    name: "world",
                    title: "World",
                    icon: "mdi-earth"
                },
                {
                    name: "history",
                    title: "History",
                    icon: "mdi-clock",
                },
                {
                    name: "contextdb",
                    title: "Context",
                    icon: "mdi-book-open-page-variant"
                },
                {
                    name: "pins",
                    title: "Pins",
                    icon: "mdi-pin"
                },
                {
                    name: "suggestions",
                    title: "Suggestions",
                    icon: "mdi-lightbulb-on"
                },
                {
                    name: "templates",
                    title: "Templates",
                    icon: "mdi-cube-scan"
                },
            ],
            requireSceneSave: false,
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
            characterList: {
                characters: [],
            },
            characterDetails: {},
            worldContext: {},
            pins: {},
            generationOptions: {},
            worldEntries: {},
            worldStates: {},

            // load writing style template
            loadWritingStyleTemplate: true,
        }
    },
    emits: [
        'navigate-r',
        'selected-character',
    ],
    watch: {
        dialog(val) {
            if (val === false) {
                this.saveOnExit();
            }
        },
        tab(val) {
            this.$nextTick(() => {
                this.emitEditorState(val)
            });

            if(val === 'world') {
                this.$nextTick(() => {
                    this.requestWorld()
                });
            } else if(val === 'history') {
                this.$nextTick(() => {
                    this.$refs.history.requestSceneHistory()
                });
            } else if(val === 'pins') {
                this.$nextTick(() => {
                    this.requestPins()
                });
            } else if(val === 'characters') {
                this.$nextTick(() => {
                    this.requestCharacterList()
                });
            } else if(val === 'templates') {
                this.$nextTick(() => {
                    this.requestTemplates()
                });
            } else if(val === 'suggestions') {
                this.$nextTick(() => {
                    this.$refs.suggestions.requestSuggestions()
                });
            }
        },
        characterDetails() {
            if (this.deferedNavigation !== null) {
                const deferedNavigation = {...this.deferedNavigation}
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
            loadContextDBEntry: this.loadContextDBEntry,
            emitEditorState: this.emitEditorState,
            showManagerEditor: this.show,
            requestPins: this.requestPins,
            requestTemplates: this.requestTemplates,
            requestWorld: this.requestWorld,
        }
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'setWaitingForInput',
        'openCharacterSheet',
        'characterSheet',
        'isInputDisabled',
        'autocompleteRequest',
        'autocompleteInfoMessage',
    ],
    methods: {

        updateGenerationOptions(options) {
            this.generationOptions = options;
        },

    
        emitEditorState(tab, meta) {

            if(meta === undefined) {
                meta = {}
            }

            meta['manager'] = this;

            // select tool based on tab ($refs)
            let tool = null;

            if(tab === 'characters') {
                tool = this.$refs.characters;
            } else if(tab === 'world') {
                tool = this.$refs.world;
            } else if(tab === 'contextdb') {
                tool = this.$refs.contextdb;
            } else if(tab === 'history') {
                tool = this.$refs.history;
            } else if(tab === 'pins') {
                tool = this.$refs.pins;
            } else if(tab === 'suggestions') {
                tool = this.$refs.suggestions;
            } else if(tab === 'templates') {
                tool = this.$refs.templates;
            }

            if(tool) {
                meta['tool'] = tool;
            }

            // if the tool as a shareState method, call it on the meta object
            if(tool && tool.shareState) {
                tool.shareState(meta);
            }

            this.$emit('navigate-r', tab || this.tab, meta);
        },

        getEditor(refName) {
            if(this.$refs[refName]) {
                return this.$refs[refName];
            }
        },

        show(tab, sub1, sub2, sub3) {
            //this.reset();
            this.requestCharacterList();
            this.requestPins();
            this.requestTemplates();
            this.requestWorld();

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
            } else if (tab == 'templates') {
                this.$nextTick(() => {
                    this.$refs.templates.selectTemplate(sub1);
                });
            } else if (tab == 'contextdb') {
                if (sub1 != null) {
                    this.$nextTick(() => {
                        this.loadContextDBEntry(sub1);
                    });
                }
            } else if (tab == 'history') {
                this.$nextTick(() => {
                    this.$refs.history.requestSceneHistory()
                });
            } else if (tab == 'suggestions') {
                this.$nextTick(() => {
                    if(sub1) {
                        this.$refs.suggestions.selectSuggestionViaMenu(sub1)
                    }
                });
            }

            this.$nextTick(() => {
                this.emitEditorState(tab)
            });
        },
        reset() {
            this.characterList = {
                characters: [],
            };
            this.characterDetails = {};
            this.pins = {};
            this.deferSelectedCharacter = null;
            this.deferedNavigation = null;
            this.tab = 'scene';
            this.loadWritingStyleTemplate = true;

            if(this.$refs.characters) {
                this.$refs.characters.reset()
            }
            if(this.$refs.world) {
                this.$refs.world.reset()
            }
            if(this.$refs.contextdb) {
                this.$refs.contextdb.reset()
            }
            if(this.$refs.pins) {
                this.$refs.pins.reset()
            }
            if(this.$refs.history) {
                this.$refs.history.reset()
            }
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

        saveScene(copy) {

            if(copy === true) {
                this.$refs.requestSaveCopyName.openDialog();
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_scene',
                save_as: copy ? copy : null,
                project_name: this.scene.data.filename ? this.scene.data.name : this.scene.data.title
            }));
        },

        // characters

        requestCharacterList() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_list',
            }));
        },

        requestCharacter(name) {

            if(name === "$NEW") {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_details',
                name: name,
            }));
        },

        newCharacter(character) {
            if(this.$refs.characters) {
                this.$refs.characters.newCharacter(character)
                this.tab = 'characters'
            }
        },

        selectCharacter(name) {
            this.tab = 'characters';
            this.$nextTick(() => {
                this.$refs.characters.selectCharacter(name)
            });
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
                if(entryId) {
                    this.$refs.contextdb.load(entryId);
                }
            });
        },

        // pins

        requestPins() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_pins',
            }));
        },

        // world

        requestWorld: function () {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_world',
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
            // Scene loaded
            if (message.type === "system" && message.id === 'scene.loaded') {
                this.reset()
            }
            if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'character_list') {
                this.characterList = message.data;
            }
            else if (message.action === 'pins') {
                this.pins = message.data.pins;
            }
            else if (message.action == 'templates') {
                this.templates = message.data;
                this.$nextTick(() => {
                    if(this.loadWritingStyleTemplate && this.scene.data && this.scene.data.writing_style_template) {
                        this.$refs.generationOptions.loadWritingStyle(this.scene.data.writing_style_template);
                        this.loadWritingStyleTemplate = false;
                    }
                });
            }
            else if(message.action === 'character_deleted') {
                this.requestCharacterList()
            }
            else if(message.action === 'character_deactivated' || message.action === 'character_activated') {
                this.requestCharacterList()
            }
            else if (message.action === 'character_details') {
                this.characterDetails = message.data;
            }
            else if (message.action === 'world') {
                this.worldEntries = message.data.entries;
                this.worldStates = message.data.reinforcements;
            }
        },
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
        this.emitEditorState(this.tab)
    },
}
</script>

<style scoped>.inactive {
    opacity: 0.5;
}

.pre-wrap {
    white-space: pre-wrap;
}</style>

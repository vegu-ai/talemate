<template>
    <v-menu max-width="500px">
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon variant="text">
                <v-icon>mdi-earth</v-icon>
            </v-btn>
        </template>
        <v-list>

            <v-list-subheader>Automatic state updates</v-list-subheader>

            <!-- update world state -->
            <v-list-item density="compact" prepend-icon="mdi-refresh" @click="updateWorlState()">
                <v-list-item-title>Update world snapshot</v-list-item-title>
                <v-list-item-subtitle>Refresh the current world state snapshot</v-list-item-subtitle>
            </v-list-item>

            <!-- add tracked world state -->
            <v-list-item density="compact" prepend-icon="mdi-cube-scan" @click="$refs.createWorldState.open()">
                <v-list-item-title>Add tracked world state</v-list-item-title>
                <v-list-item-subtitle>Track and auto-update a world state</v-list-item-subtitle>
            </v-list-item>

            <!-- add tracked character state -->
            <v-list-item density="compact" prepend-icon="mdi-account-search" @click="$refs.createCharacterState.open()">
                <v-list-item-title>Add tracked character state</v-list-item-title>
                <v-list-item-subtitle>Track and auto-update a character state</v-list-item-subtitle>
            </v-list-item>

            <!-- player character submenu -->
            <v-menu v-if="getPlayerCharacterName() && characterSubmenuItems(getPlayerCharacterName(), true).length > 0" open-on-hover location="end">
                <template v-slot:activator="{ props }">
                    <v-list-item v-bind="props" @click.stop prepend-icon="mdi-account-tie" append-icon="mdi-chevron-right">
                        <v-list-item-title>{{ getPlayerCharacterName() }}</v-list-item-title>
                    </v-list-item>
                </template>
                <v-list>
                    <v-list-item v-for="(item, index) in characterSubmenuItems(getPlayerCharacterName(), true)" :key="index"
                        @click="handleClickCharacterSubmenuItem(item, getPlayerCharacterName())">
                        <template v-slot:append>
                            <v-icon v-if="item.tracked" color="success">mdi-check-circle-outline</v-icon>
                        </template>
                        <v-list-item-title>{{ item.name }}</v-list-item-title>
                        <v-list-item-subtitle v-if="item.description">{{ item.description }}</v-list-item-subtitle>
                    </v-list-item>
                </v-list>
            </v-menu>

            <!-- npc character submenus -->
            <template v-for="npc_name in npcCharacters" :key="npc_name">
                <v-menu v-if="characterSubmenuItems(npc_name, false).length > 0" open-on-hover location="end">
                    <template v-slot:activator="{ props }">
                        <v-list-item v-bind="props" @click.stop prepend-icon="mdi-account" append-icon="mdi-chevron-right">
                            <v-list-item-title>{{ npc_name }}</v-list-item-title>
                        </v-list-item>
                    </template>
                    <v-list>
                        <v-list-item v-for="(item, index) in characterSubmenuItems(npc_name, false)" :key="index"
                            @click="handleClickCharacterSubmenuItem(item, npc_name)">
                            <template v-slot:append>
                                <v-icon v-if="item.tracked" color="success">mdi-check-circle-outline</v-icon>
                            </template>
                            <v-list-item-title>{{ item.name }}</v-list-item-title>
                            <v-list-item-subtitle v-if="item.description">{{ item.description }}</v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                </v-menu>
            </template>

            <!-- world state submenu -->
            <v-menu v-if="worldSubmenuItems().length > 0" open-on-hover location="end">
                <template v-slot:activator="{ props }">
                    <v-list-item v-bind="props" @click.stop prepend-icon="mdi-earth" append-icon="mdi-chevron-right">
                        <v-list-item-title>World</v-list-item-title>
                    </v-list-item>
                </template>
                <v-list>
                    <v-list-item v-for="(item, index) in worldSubmenuItems()" :key="index"
                        @click="handleClickWorldSubmenuItem(item)">
                        <template v-slot:append>
                            <v-icon v-if="item.tracked" color="success">mdi-check-circle-outline</v-icon>
                        </template>
                        <v-list-item-title>{{ item.name }}</v-list-item-title>
                        <v-list-item-subtitle v-if="item.description">{{ item.description }}</v-list-item-subtitle>
                    </v-list-item>
                </v-list>
            </v-menu>

            <v-divider class="my-1"></v-divider>

            <v-list-subheader>World context</v-list-subheader>

            <!-- generate world context -->
            <v-list-item density="compact" prepend-icon="mdi-auto-fix" @click="$refs.generateWorldContext.open()">
                <v-list-item-title>Generate world context</v-list-item-title>
                <v-list-item-subtitle>Generate a new world entry from current scene context</v-list-item-subtitle>
            </v-list-item>

            <!-- open world editor -->
            <v-list-item density="compact" prepend-icon="mdi-earth" @click="$emit('open-world-state-manager', 'world')">
                <v-list-item-title>World context editor</v-list-item-title>
                <v-list-item-subtitle>Open the world state manager</v-list-item-subtitle>
            </v-list-item>

            <!-- open character editor -->
            <v-list-item density="compact" prepend-icon="mdi-account-details" @click="$emit('open-world-state-manager', 'characters')">
                <v-list-item-title>Character context editor</v-list-item-title>
                <v-list-item-subtitle>Open the character editor</v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>

    <ContextualGenerateFromTopic
        ref="generateWorldContext"
        context-prefix="world context"
        title="Generate World Context"
        description="Generate a new world entry based on the current scene context. Use this for locations, lore, backstory, and other world details. Character context should be handled via the character editor."
        topic-label="Topic / Title"
        topic-hint="The topic or title for the world entry (will be used as the entry ID)"
        @generate="saveGeneratedWorldEntry"
    />

    <QuickCreateStateReinforcement
        ref="createWorldState"
        title="Add Tracked World State"
        description="Create a tracked world state that the AI will automatically monitor and update at a regular interval. Once created, the state can be found and managed in the World State Manager under the World States tab."
        :insertion-modes="insertionModes"
        default-insert="never"
        @create="createWorldStateReinforcement"
    />

    <QuickCreateStateReinforcement
        ref="createCharacterState"
        title="Add Tracked Character State"
        description="Create a tracked character state that the AI will automatically monitor and update at a regular interval. Once created, the state can be found and managed in the World State Manager under the character's Tracked States tab."
        :insertion-modes="insertionModes"
        :characters="allCharacters"
        default-insert="sequential"
        @create="createCharacterStateReinforcement"
    />
</template>

<script>
import ContextualGenerateFromTopic from './ContextualGenerateFromTopic.vue';
import QuickCreateStateReinforcement from './QuickCreateStateReinforcement.vue';

export default {
    name: 'SceneToolsWorld',
    components: {
        ContextualGenerateFromTopic,
        QuickCreateStateReinforcement,
    },
    props: {
        disabled: Boolean,
        npcCharacters: Array,
        worldStateTemplates: Object,
    },
    data() {
        return {
            insertionModes: [
                { "title": "Passive", "value": "never", "props": { "subtitle": "Rely on pins and relevancy attachment" } },
                { "title": "Sequential", "value": "sequential", "props": { "subtitle": "Insert into current scene progression" } },
                { "title": "Conversation Context", "value": "conversation-context", "props": { "subtitle": "Insert into conversation context for this character" } },
            ],
        }
    },
    inject: [
        'getWebsocket',
        'getTrackedCharacterState',
        'getTrackedCharacterStates',
        'getTrackedWorldState',
        'getTrackedWorldStates',
        'getPlayerCharacterName',
        'formatWorldStateTemplateString',
    ],
    computed: {
        allCharacters() {
            let characters = [...(this.npcCharacters || [])];
            let player = this.getPlayerCharacterName();
            if (player) {
                characters.unshift(player);
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
    },
    methods: {
        handleClickWorldStateTemplate(template, character_name) {
            let query = this.formatWorldStateTemplateString(template.query, character_name);

            if (character_name) {
                let stateActive = this.getTrackedCharacterState(character_name, query) !== null;
                if (stateActive) {
                    this.$emit('open-world-state-manager', 'characters', character_name, 'reinforce', query);
                } else {
                    this.getWebsocket().send(JSON.stringify({
                        type: 'world_state_manager',
                        action: 'apply_template',
                        template: template,
                        character_name: character_name,
                        run_immediately: true,
                    }));
                }
            } else {
                let stateActive = this.getTrackedWorldState(query) !== null;
                if (stateActive) {
                    this.$emit('open-world-state-manager', 'world', 'state:' + query);
                } else {
                    this.getWebsocket().send(JSON.stringify({
                        type: 'world_state_manager',
                        action: 'apply_template',
                        template: template,
                        character_name: null,
                        run_immediately: true,
                    }));
                }
            }
        },

        worldStateReinforcementFavoriteExists() {
            for (let template of this.worldStateReinforcementTemplates) {
                if (template.favorite) {
                    return true;
                }
            }
            return false;
        },

        worldStateReinforcementFavoritesForWorldEntry() {
            let favorites = [];
            for (let template of this.worldStateReinforcementTemplates) {
                if (template.favorite && template.state_type == 'world') {
                    favorites.push(template);
                }
            }
            return favorites;
        },

        worldStateReinforcementFavoritesForNPCs() {
            let favorites = [];
            for (let template of this.worldStateReinforcementTemplates) {
                if (template.favorite && (template.state_type == 'npc' || template.state_type == 'character')) {
                    favorites.push(template);
                }
            }
            return favorites;
        },

        worldStateReinforcementFavoritesForPlayer() {
            let favorites = [];
            for (let template of this.worldStateReinforcementTemplates) {
                if (template.favorite && (template.state_type == 'player' || template.state_type == 'character')) {
                    favorites.push(template);
                }
            }
            return favorites;
        },

        characterSubmenuItems(characterName, isPlayer) {
            let items = [];
            let seenQueries = new Set();

            // add favorite templates first
            let favorites = isPlayer ? this.worldStateReinforcementFavoritesForPlayer() : this.worldStateReinforcementFavoritesForNPCs();
            for (let template of favorites) {
                let query = this.formatWorldStateTemplateString(template.query, characterName);
                seenQueries.add(query);
                items.push({
                    type: 'template',
                    template: template,
                    query: query,
                    name: template.name,
                    description: template.description,
                    tracked: this.getTrackedCharacterState(characterName, query) !== null,
                });
            }

            // add tracked states that aren't already covered by a template
            let trackedStates = this.getTrackedCharacterStates(characterName) || [];
            for (let state of trackedStates) {
                if (!seenQueries.has(state.question)) {
                    items.push({
                        type: 'tracked',
                        query: state.question,
                        name: state.question,
                        description: '',
                        tracked: true,
                    });
                }
            }

            return items;
        },

        worldSubmenuItems() {
            let items = [];
            let seenQueries = new Set();

            // add favorite templates first
            for (let template of this.worldStateReinforcementFavoritesForWorldEntry()) {
                let query = this.formatWorldStateTemplateString(template.query);
                seenQueries.add(query);
                items.push({
                    type: 'template',
                    template: template,
                    query: query,
                    name: template.name,
                    description: template.description,
                    tracked: this.getTrackedWorldState(query) !== null,
                });
            }

            // add tracked states that aren't already covered by a template
            let trackedStates = this.getTrackedWorldStates() || [];
            for (let state of trackedStates) {
                if (!seenQueries.has(state.question)) {
                    items.push({
                        type: 'tracked',
                        query: state.question,
                        name: state.question,
                        description: '',
                        tracked: true,
                    });
                }
            }

            return items;
        },

        handleClickWorldSubmenuItem(item) {
            if (item.tracked) {
                this.$emit('open-world-state-manager', 'world', 'state:' + item.query);
            } else if (item.template) {
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'apply_template',
                    template: item.template,
                    character_name: null,
                    run_immediately: true,
                }));
            }
        },

        handleClickCharacterSubmenuItem(item, characterName) {
            if (item.tracked) {
                this.$emit('open-world-state-manager', 'characters', characterName, 'reinforce', item.query);
            } else if (item.template) {
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'apply_template',
                    template: item.template,
                    character_name: characterName,
                    run_immediately: true,
                }));
            }
        },

        updateWorlState() {
            this.getWebsocket().send(JSON.stringify({ type: 'world_state_agent', action: 'request_update' }));
        },

        saveGeneratedWorldEntry(topic, content) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_world_entry',
                id: topic,
                text: content,
                meta: {},
            }));
        },

        createWorldStateReinforcement(data) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_world_state_reinforcement',
                question: data.question,
                answer: '',
                instructions: data.instructions,
                interval: data.interval,
                insert: data.insert,
                update_state: true,
            }));
        },

        createCharacterStateReinforcement(data) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_character_detail_reinforcement',
                name: data.character,
                question: data.question,
                answer: '',
                instructions: data.instructions,
                interval: data.interval,
                insert: data.insert,
                require_active: data.require_active,
                update_state: true,
            }));
        },
    },
    emits: ['open-world-state-manager'],
}
</script>

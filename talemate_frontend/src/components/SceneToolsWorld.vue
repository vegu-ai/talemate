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
                <v-list-item-title>Update the world state</v-list-item-title>
                <v-list-item-subtitle>Refresh the current world state snapshot</v-list-item-subtitle>
            </v-list-item>

            <div v-if="!worldStateReinforcementFavoriteExists()">
                <v-alert dense variant="text" color="grey" icon="mdi-cube-scan">
                    <span>There are no favorite world state templates. You can add them in the <b>World State Manager</b>. Favorites will be shown here.
                    </span>
                </v-alert>
            </div>
            <div v-else>

                <!-- character templates -->

                <div v-for="npc_name in npcCharacters" :key="npc_name">
                    <v-list-item v-for="(template, index) in worldStateReinforcementFavoritesForNPCs()" :key="index"
                        @click="handleClickWorldStateTemplate(template, npc_name)"
                        prepend-icon="mdi-account">
                        <template v-slot:append>
                            <v-icon v-if="getTrackedCharacterState(npc_name, template.query) !== null" color="success">mdi-check-circle-outline</v-icon>
                        </template>
                        <v-list-item-title>{{ template.name }} ({{ npc_name }})</v-list-item-title>
                        <v-list-item-subtitle>{{ template.description }}</v-list-item-subtitle>
                    </v-list-item>
                </div>

                <!-- player templates -->

                <v-list-item v-for="(template, index) in worldStateReinforcementFavoritesForPlayer()" :key="'player' + index"
                    @click="handleClickWorldStateTemplate(template, getPlayerCharacterName())"
                    prepend-icon="mdi-account-tie">
                    <template v-slot:append>
                        <v-icon v-if="getTrackedCharacterState(getPlayerCharacterName(), template.query) !== null" color="success">mdi-check-circle-outline</v-icon>
                    </template>
                    <v-list-item-title>{{ template.name }} ({{ getPlayerCharacterName() }})</v-list-item-title>
                    <v-list-item-subtitle>
                        {{ template.description }}
                    </v-list-item-subtitle>
                </v-list-item>

                <!-- world entry templates -->

                <v-list-item v-for="(template, index) in worldStateReinforcementFavoritesForWorldEntry()" :key="'worldEntry' + index"
                    @click="handleClickWorldStateTemplate(template)"
                    prepend-icon="mdi-earth">
                    <template v-slot:append>
                        <v-icon v-if="getTrackedWorldState(template.query) !== null" color="success">mdi-check-circle-outline</v-icon>
                    </template>
                    <v-list-item-title>{{ template.name }}</v-list-item-title>
                    <v-list-item-subtitle>{{ template.description }}</v-list-item-subtitle>
                </v-list-item>

            </div>

            <v-divider class="my-1"></v-divider>

            <v-list-subheader>World context</v-list-subheader>

            <!-- generate world context -->
            <v-list-item density="compact" prepend-icon="mdi-auto-fix" @click="$refs.generateWorldContext.open()">
                <v-list-item-title>Generate world context</v-list-item-title>
                <v-list-item-subtitle>Generate a new world entry from current scene context</v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>

    <ContextualGenerateFromTopic
        ref="generateWorldContext"
        context-prefix="world context"
        title="Generate World Context"
        description="Generate a new world entry based on the current scene context. Provide a topic and optional instructions to guide the generation."
        topic-label="Topic / Title"
        topic-hint="The topic or title for the world entry (will be used as the entry ID)"
        @generate="saveGeneratedWorldEntry"
    />
</template>

<script>
import ContextualGenerateFromTopic from './ContextualGenerateFromTopic.vue';

export default {
    name: 'SceneToolsWorld',
    components: {
        ContextualGenerateFromTopic,
    },
    props: {
        disabled: Boolean,
        npcCharacters: Array,
        worldStateTemplates: Object,
    },
    inject: [
        'getWebsocket',
        'getTrackedCharacterState',
        'getTrackedWorldState',
        'getPlayerCharacterName',
        'formatWorldStateTemplateString',
    ],
    computed: {
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
                    this.$emit('open-world-state-manager', 'world', 'states', query);
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
                if (template.favorite && template.state_type == 'player' || template.state_type == 'character') {
                    favorites.push(template);
                }
            }
            return favorites;
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
    },
    emits: ['open-world-state-manager'],
}
</script>

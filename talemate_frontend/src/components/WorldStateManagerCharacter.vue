<template>
    <v-card flat>
        <v-card-text>
            <v-row>
                <v-col cols="2">
                    <v-tabs density="compact" direction="vertical" v-model="selectedCharacter" color="indigo-lighten-3">
                        <v-tab prepend-icon="mdi-account" v-for="character in characterList.characters" :key="character.name"
                            @click="loadCharacter(character.name)" :value="character.name">
                            <div class="text-left text-caption">
                                {{ character.name }}
                                <div class="text-caption">
                                <v-chip v-if="character.is_player === true" label size="x-small"
                                    variant="tonal" color="info">Player</v-chip>
                                <v-chip v-else-if="character.is_player === false" label size="x-small"
                                    variant="tonal" color="warning">AI</v-chip>
                                <v-chip v-if="character.active === true && character.is_player === false"
                                    label size="x-small" variant="tonal" color="success"
                                    class="ml-1">Active</v-chip>
                                </div>

                            </div>
                        </v-tab>
                    </v-tabs>
                </v-col>
                <v-col cols="10">
                    <div v-if="selectedCharacter !== null">
                        <v-card>

                            <v-card-title>
                                <v-icon size="small">mdi-account</v-icon>
                                {{ character.name }}
                                <v-chip size="x-small" v-if="character.is_player === false" color="warning" label>AI</v-chip>
                                <v-chip size="x-small" v-if="character.is_player === true" color="info" label>Player</v-chip>
                                <v-chip size="x-small" class="ml-1" v-if="character.active === true && character.is_player === false" color="success" label>Active</v-chip>
                        
                            </v-card-title>

                            <v-divider></v-divider>
                            
                            <v-tabs v-model="page" color="primary" density="compact">
                                <v-tab value="description">
                                    <v-icon size="small">mdi-text-account</v-icon>
                                    Description
                                </v-tab>
                                <v-tab value="attributes">
                                    <v-icon size="small">mdi-format-list-bulleted-type</v-icon>
                                    Attributes
                                </v-tab>
                                <v-tab value="details">
                                    <v-icon size="small">mdi-format-list-text</v-icon>
                                    Details
                                </v-tab>
                                <v-tab value="reinforce">
                                    <v-icon size="small">mdi-image-auto-adjust</v-icon>
                                    States
                                </v-tab>
                                <v-tab value="actor" :disabled="character.is_player">
                                    <v-icon size="small">mdi-bullhorn</v-icon>
                                    Actor
                                </v-tab>
                            </v-tabs>
                        
                            <v-card-text>
                                <v-tabs-window v-model="page">
                                    <v-tabs-window-item value="description">
                                        <WorldStateManagerCharacterDescription 
                                        ref="description" 
                                        @require-scene-save="$emit('require-scene-save')"
                                        :immutable-character="character" />
                                    </v-tabs-window-item>
                                    <v-tabs-window-item value="attributes">
                                        <WorldStateManagerCharacterAttributes 
                                        ref="attributes" 
                                        @require-scene-save="$emit('require-scene-save')"
                                        :immutable-character="character" />
                                    </v-tabs-window-item>
                                    <v-tabs-window-item value="details">
                                        <WorldStateManagerCharacterDetails
                                        ref="details" 
                                        @require-scene-save="$emit('require-scene-save')"
                                        @load-character-state-reinforcement="onLoadCharacterStateReinforcement"
                                        :immutable-character="character" />
                                    </v-tabs-window-item>
                                    <v-tabs-window-item value="reinforce">
                                        <WorldStateManagerCharacterReinforcements
                                        ref="reinforcements" 
                                        @require-scene-save="$emit('require-scene-save')"
                                        :templates="templates"
                                        :immutable-character="character" />
                                    </v-tabs-window-item>
                                    <v-tabs-window-item value="actor">
                                        <WorldStateManagerCharacterActor
                                        ref="reinforcements" 
                                        @require-scene-save="$emit('require-scene-save')"
                                        :character="character" />
                                    </v-tabs-window-item>
                                </v-tabs-window>
                            </v-card-text>
                        </v-card>


                    </div>
                    <v-alert v-else type="info" color="grey" variant="text" icon="mdi-account">
                        Manage character attributes and add extra details.
                        <br><br>
                        You can also set up automatic reinforcement of character states. This will cause the
                        AI to regularly re-evaluate the state and update the detail accordingly.
                        <br><br>
                        Select a character from the list on the left to get started.
                    </v-alert>
                </v-col>
            </v-row>
        </v-card-text>
    </v-card>
</template>
<script>

import WorldStateManagerCharacterAttributes from './WorldStateManagerCharacterAttributes.vue';
import WorldStateManagerCharacterDescription from './WorldStateManagerCharacterDescription.vue';
import WorldStateManagerCharacterDetails from './WorldStateManagerCharacterDetails.vue';
import WorldStateManagerCharacterReinforcements from './WorldStateManagerCharacterReinforcements.vue';
import WorldStateManagerCharacterActor from './WorldStateManagerCharacterActor.vue';

export default {
    name: 'WorldStateManagerCharacter',
    components: {
        WorldStateManagerCharacterAttributes,
        WorldStateManagerCharacterDescription,
        WorldStateManagerCharacterDetails,
        WorldStateManagerCharacterReinforcements,
        WorldStateManagerCharacterActor,
    },
    props: {
        characterList: Object,
        templates: Object,
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
    ],
    data() {
        return {
            page: 'description',
            selectedCharacter: null,
            character: {},
        }
    },
    emits:[
        'require-scene-save'
    ],
    methods: {

        onLoadCharacterStateReinforcement(name) {
            this.page = 'reinforce'
            this.$nextTick(() => {
                this.$refs.reinforcements.loadWithRequire(name);
            });
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
            this.page = 'description';
            this.selectedCharacter = name;
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
            else if (message.action === 'character_details') {
                this.character = message.data;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>
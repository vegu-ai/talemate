<template>
    <v-card flat>

        <div v-if="selected !== null && character">
            <v-card-title>
                <v-icon size="small">mdi-account</v-icon>
                {{ character.name }}
                <v-chip size="x-small" v-if="character.is_player === false" color="warning" label>AI</v-chip>
                <v-chip size="x-small" v-if="character.is_player === true" color="info" label>Player</v-chip>
                <v-chip size="x-small" class="ml-1" v-if="character.active === true && character.is_player === false" color="success" label>Active</v-chip>
        
            </v-card-title>

            <v-divider></v-divider>
        </div>

        <v-card-text>

            <div v-if="selected !== null && character">
                <v-row>
                    <v-col cols="12" md="3" xl="2">
                        <CoverImage v-if="character !== null" ref="coverImageCharacter" :target="character" :type="'character'" :allow-update="true" />

                        <v-list v-if="character !== null && !character.is_player">
                            
                            <!-- DEACTIVATE CHARACTER -->
                    
                            <v-list-item v-if="character.active">
                                <v-tooltip max-width="300" :text="`Immediately deactivate ${character.name}. This will remove the character from the scene, but it will still be available in the character list, and can be recalled at any point.`">
                                    <template v-slot:activator="{ props }">
                                        <v-btn @click.stop="deactivateCharacter" v-bind="props" variant="tonal" block color="secondary" prepend-icon="mdi-exit-run">Deactivate</v-btn>
                    
                                    </template>
                                </v-tooltip>
                            </v-list-item>
                    
                            <v-list-item v-else>
                                <v-tooltip max-width="300" :text="`Immediately activate ${character.name}. This will re-add them to the scene and allow to participate in it.`">
                                    <template v-slot:activator="{ props }">
                                        <v-btn @click.stop="activateCharacter" v-bind="props" variant="tonal" block color="primary" prepend-icon="mdi-human-greeting">Activate</v-btn>
                                    </template>
                                </v-tooltip>
                            </v-list-item>
                    
                            <v-divider></v-divider>
                    
                            <!-- DELETE CHARACTER -->
                    
                            <v-list-item>
                                <v-tooltip  v-if="confirmDelete === null"  max-width="300" :text="`Permanently delete ${character.name} - will ask for confirmation and cannot be undone.`">
                                    <template v-slot:activator="{ props }">
                                        <v-btn @click.stop="confirmDelete=''" variant="tonal" v-bind="props" block color="red-darken-2" prepend-icon="mdi-close-box-outline">Delete</v-btn>
                                    </template>
                                </v-tooltip>
                    
                                <div v-else class="mt-2">
                                    <v-list-item-subtitle>Confirm Deletion</v-list-item-subtitle>
                                    <p class="text-grey text-caption">
                                        Confirm that you want to delete <span class="text-primary">{{ character.name }}</span>, by
                                        typing the character name and clicking <span class="text-red-darken-2">Delete</span> once more.
                                        This cannot be undone.
                                    </p>
                                    <v-text-field :disabled="deleteBusy" v-model="confirmDelete" color="red-darken-2" hide-details @keydown.enter="deleteCharacter" />
                                    <v-btn v-if="confirmDelete !== character.name" :disabled="deleteBusy" variant="tonal" block color="secondary" prepend-icon="mdi-cancel" @click.stop="confirmDelete = null">Cancel</v-btn>
                                    <v-btn v-else :disabled="deleteBusy" variant="tonal" block color="red-darken-2" prepend-icon="mdi-close-box-outline" @click.stop="deleteCharacter">Delete</v-btn>
                                </div>
                            </v-list-item>
                        </v-list>
                    </v-col>
                    <v-col cols="12" md="9" xl="10">
                            <v-card>

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
                                    <!--
                                    <v-tab value="actor" :disabled="true">
                                        <v-icon size="small">mdi-image</v-icon>
                                        Images
                                    </v-tab>
                                    -->
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



                    </v-col>
                </v-row>
            </div>
            <v-alert v-else type="info" color="grey" variant="text" icon="mdi-account">
                Manage character attributes and add extra details.
                <br><br>
                You can also set up automatic reinforcement of character states. This will cause the
                AI to regularly re-evaluate the state and update the detail accordingly.
                <br><br>
                Select a character from the list on the left to get started.
            </v-alert>
        </v-card-text>
    </v-card>
</template>
<script>
import CoverImage from './CoverImage.vue';

import WorldStateManagerCharacterAttributes from './WorldStateManagerCharacterAttributes.vue';
import WorldStateManagerCharacterDescription from './WorldStateManagerCharacterDescription.vue';
import WorldStateManagerCharacterDetails from './WorldStateManagerCharacterDetails.vue';
import WorldStateManagerCharacterReinforcements from './WorldStateManagerCharacterReinforcements.vue';
import WorldStateManagerCharacterActor from './WorldStateManagerCharacterActor.vue';

export default {
    name: 'WorldStateManagerCharacter',
    components: {
        CoverImage,
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
            selected: null,
            character: null,
            confirmDelete: null,
            deleteBusy: false,
        }
    },
    emits:[
        'require-scene-save',
        'selected-character',
    ],
    methods: {

        reset() {
            this.selected = null;
            this.character = null;
            this.page = 'description';
            if(this.$refs.attributes)
                this.$refs.attributes.reset()
        },

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
            this.selected = name;
        },

        deleteCharacter() {
            if (this.confirmDelete === this.character.name) {
                this.deleteBusy = true;
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'delete_character',
                    name: this.character.name,
                }));
            }
        },
        deactivateCharacter() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'deactivate_character',
                name: this.character.name,
            }));
        },
        activateCharacter() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'activate_character',
                name: this.character.name,
            }));
        },

        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
            else if (message.action === 'character_details') {
                this.character = message.data;
                this.$emit('selected-character', this.character)
            } else if(message.action === 'character_deleted') {
                if(this.selected === message.data.name) {
                    this.reset();
                }
                this.deleteBusy = false;
                this.confirmDelete = null;
            } else if(message.action === 'character_deactivated' || message.action === 'character_activated') {
                if(this.selected === message.data.name) {
                    this.loadCharacter(this.selected)
                }
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>
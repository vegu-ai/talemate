<template>

    <v-card flat>

        <div v-if="selected !== null && character">
            <v-card-title>
                <v-icon size="small">mdi-account</v-icon>
                {{ character.name }}
                <v-chip size="x-small" v-if="character.is_player === false" color="warning" label>AI</v-chip>
                <v-chip size="x-small" v-if="character.is_player === true" color="info" label>Player</v-chip>
                <v-chip size="x-small" class="ml-1" v-if="character.active === true && character.is_player === false" color="success" label>Active</v-chip>
                
                <v-tooltip text="Change the name color for this character." v-if="!character.is_new">
                    <template v-slot:activator="{ props }">
                        <v-chip v-bind="props" size="x-small" label class="ml-1" :style="`color: ${character.color}`" prepend-icon="mdi-brush" @click.stop="characterColorPicker=true" variant="tonal">{{  character.color  }}</v-chip>
                    </template>
                </v-tooltip>


                <v-dialog v-model="characterColorPicker" scrollable width="300">
                    <v-color-picker v-model="character.color" @update:model-value="onCharacterColorChange"></v-color-picker>
                </v-dialog>
            </v-card-title>

        </div>
        <div v-else-if="character && character.is_new">
            <v-card-title>
                <v-icon size="small">mdi-account-plus</v-icon>
                Create New Character
            </v-card-title>
        </div>

        <v-card-text>

            <div v-if="character && character.is_new">
                <WorldStateManagerCharacterCreator
                ref="creator"
                @require-scene-save="$emit('require-scene-save')"
                @cancelled="reset"
                @character-created="onCharacterCreated"
                :generation-options="generationOptions"
                :scene="scene"
                :templates="templates" />
            </div>

            <div v-else-if="selected !== null && character">
                <v-row>
                    <v-col cols="12" md="3" xl="2">
                        <CoverImage v-if="character !== null" ref="coverImageCharacter" :target="character" :type="'character'" :allow-update="true" :collapsable="false" />
                        <p v-if="coverImageBusy">
                            <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
                        </p>
                        <v-list v-if="character !== null">
                            
                            <!-- GENERATE COVER IMAGE -->

                            <v-list-item>
                                <v-tooltip max-width="300" :text="`Generate a new cover image for ${character.name}. This will be used as the main image for the character.`">
                                    <template v-slot:activator="{ props }">
                                        <v-btn :disabled="!agentStatus.visual || !agentStatus.visual.ready" @click.stop="visualizeCharacter" v-bind="props" variant="tonal" block color="primary" prepend-icon="mdi-image-filter-center-focus">Generate Image</v-btn>
                                    </template>
                                </v-tooltip>
                            </v-list-item>

                        </v-list>
                            
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

                                <v-divider></v-divider>
                            
                                <v-card-text>
                                    <v-tabs-window v-model="page">
                                        <v-tabs-window-item value="description">
                                            <WorldStateManagerCharacterDescription 
                                            ref="description" 
                                            @require-scene-save="$emit('require-scene-save')"
                                            :generation-options="generationOptions"
                                            :templates="templates"
                                            :immutable-character="character" />
                                        </v-tabs-window-item>
                                        <v-tabs-window-item value="attributes">
                                            <WorldStateManagerCharacterAttributes 
                                            ref="attributes" 
                                            @require-scene-save="$emit('require-scene-save')"
                                            :generation-options="generationOptions"
                                            :templates="templates"
                                            :immutable-character="character" />
                                        </v-tabs-window-item>
                                        <v-tabs-window-item value="details">
                                            <WorldStateManagerCharacterDetails
                                            ref="details" 
                                            @require-scene-save="$emit('require-scene-save')"
                                            @load-character-state-reinforcement="onLoadCharacterStateReinforcement"
                                            :generation-options="generationOptions"
                                            :templates="templates"
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
                                            :generation-options="generationOptions"
                                            :templates="templates"
                                            :character="character" />
                                        </v-tabs-window-item>
                                    </v-tabs-window>
                                </v-card-text>
                            </v-card>



                    </v-col>
                </v-row>
            </div>
            <v-alert v-else type="info" color="grey" variant="text" icon="mdi-account">
                <p>
                    Manage existing characters or add new ones to the scene. Characters can be AI or player controlled.
                </p>
                <p class="mt-2">
                    You can set up character attributes, descriptions, and details. 
                    You can also set up automatic reinforcement of character states. This will cause the
                    AI to regularly re-evaluate the state and update the detail accordingly.
                </p>
                <p class="mt-2">
                    Select a character from the list on the left to get started.
                </p>
            </v-alert>
        </v-card-text>
    </v-card>

    <v-card class="mt-4" density="compact" v-if="character === null">
        <v-card-title>Overview</v-card-title>
        <v-card-text class="text-grey">
            <p class="mt-4">
                <!-- Attribute description -->
                <strong class="text-grey-lighten-1">
                    <v-icon size="small" class="mr-2" color="highlight1">mdi-badge-account</v-icon>Attributes
                </strong> are low to medium detail information about the character. They range from physical attributes to personality traits.
            </p>
            <p class="mt-4">
                <!-- Details description -->
                <strong class="text-grey-lighten-1">
                    <v-icon size="small" class="mr-2" color="highlight2">mdi-account-details</v-icon>Details
                </strong> are low to high detail information about the character. They could contain information about the character's background, history, or other relevant information.
            </p>
            <p class="mt-2 text-muted">
                When a <v-icon size="small" class="mr-2" color="highlight3">mdi-image-auto-adjust</v-icon><span class="text-highlight3">state reinforcment</span> is updated the value is set to the corresponding detail.
            </p>
            <p class="mt-4">
                <!-- Character description description -->
                <strong class="text-grey-lighten-1">
                    <v-icon size="small" class="mr-2" color="grey">mdi-text-account</v-icon>Description
                </strong> is a description of the character. A summarization of their appearance, personality, and other relevant information as it relates to the scene.
            </p>
            <p class="mt-4">
                <!-- Reinforcement description -->
                <strong class="text-grey-lighten-1">
                    <v-icon size="small" class="mr-2" color="highlight3">mdi-image-auto-adjust</v-icon>States
                </strong> are the reinforcement states for the character. This is where you can set up automatic reinforcement of character states. This will cause the AI to regularly re-evaluate the state and update the detail accordingly.
            </p>
            <p class="mt-4">
                <!-- Actor description -->
                <strong class="text-grey-lighten-1">
                    <v-icon size="small" class="mr-2" color="highlight5">mdi-bullhorn</v-icon>Actor
                </strong> management lets you define acting and speaking patterns for the character via dialogue instructions and examples. This is only available for AI characters.
            </p>
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
import WorldStateManagerCharacterCreator from './WorldStateManagerCharacterCreator.vue';

export default {
    name: 'WorldStateManagerCharacter',
    components: {
        CoverImage,
        WorldStateManagerCharacterAttributes,
        WorldStateManagerCharacterDescription,
        WorldStateManagerCharacterDetails,
        WorldStateManagerCharacterReinforcements,
        WorldStateManagerCharacterActor,
        WorldStateManagerCharacterCreator,
    },
    props: {
        scene: Object,
        characterList: Object,
        templates: Object,
        agentStatus: Object,
        generationOptions: Object,
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
            coverImageBusy: false,
            characterColorPicker: false,
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

        onCharacterCreated(character) {
            this.$nextTick(() => {
                this.selected = character.name;
            });
        },

        onCharacterColorChange() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_color',
                name: this.character.name,
                color: this.character.color,
            }));
        },

        requestCharacter(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'get_character_details',
                name: name,
            }));
        },

        newCharacter(character) {
            this.character = character;
            this.$nextTick(() => {
                this.$refs.creator.setCharacter(character)
            });
        },

        loadCharacter(name) {
            this.requestCharacter(name);
            this.page = 'description';
            this.selected = name;
        },

        selectCharacter(name) {
            this.loadCharacter(name);
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
        visualizeCharacter() {
            this.coverImageBusy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'visual',
                action: 'visualize_character',
                context: {
                    character_name: this.character.name,
                    replace: true,
                }
            }));
        },

        handleMessage(message) {
            if(message.type == "image_generated") {
                this.coverImageBusy = false;
                if(message.data.context.character_name === this.character.name) {
                    this.loadCharacter(this.character.name);
                }
            }
            else if (message.type !== 'world_state_manager') {
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
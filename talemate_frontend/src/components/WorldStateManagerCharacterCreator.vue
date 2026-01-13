<template>
    <v-card>
        <v-card-text>
            <v-row>
                <v-col cols="12" lg="4" xl="3">
                    <v-card elevation="7">
                        <v-card-text>
                            <div class="text-caption text-uppercase text-muted mb-2"><v-icon>mdi-cube-scan</v-icon> Templates ({{ characterTemplateCount }})</div>
                            <WorldStateManagerTemplateApplicator
                                ref="templateApplicator"
                                :validateTemplate="validateTemplate"
                                :templates="templates"
                                source="world_state_character_creator"
                                :select-only="true"
                                :template-types="['character_attribute', 'character_detail', 'state_reinforcement']"
                                @selected="(templates) => { character.templates = templates; }"/>
                        </v-card-text>
                    </v-card>
                </v-col>
                <v-col cols="12" lg="6" xl="5">
                    <v-card elevation="7">
                        <v-card-text>
                            <v-checkbox :disabled="busy" v-model="character.generation_context.enabled" label="Enable AI Generation"></v-checkbox>
                            <div v-if="character.generation_context.enabled">
                                <v-textarea 
                                    :disabled="busy" 
                                    v-model="character.generation_context.instructions" 
                                    label="AI Generation Instructions" 
                                    auto-grow rows="3" 
                                    placeholder="A young man ..." 
                                    hint="Briefly describe the character you want to generate.">
                                </v-textarea>
                            </div>

                            <v-text-field :disabled="busy" v-model="character.name" label="Name"></v-text-field>
        
                            <v-textarea 
                                v-model="character.description" 
                                label="Description"
                                ref="description"
                                :disabled="busy || descriptionBusy"
                                :loading="descriptionBusy"
                                :hint="autocompleteInfoMessage(busy)"
                                @keyup.ctrl.enter.stop="sendAutocompleteRequest"
                                ></v-textarea>

                            <div v-if="character.generation_context.enabled">
                                <v-checkbox  density="compact" :disabled="busy" v-model="character.generation_context.generateAttributes" label="Generate attributes" messages="Generate a few attributes based on the instructions and the description."></v-checkbox>
                            </div>

                            <v-checkbox density="compact" :disabled="!canBePlayer || busy" v-model="character.is_player" label="Controlled by the player" hide-details></v-checkbox>

                            <p class="text-caption text-muted" v-if="!canBePlayer">
                                There already is a player character in this scene. Currently only one player character is supported.
                            </p>
                        </v-card-text>
                    </v-card>
                </v-col>
                <v-col cols="12" lg="2" xl="2">
                    <v-alert density="compact" variant="text" icon="mdi-auto-fix" color="muted" v-if="character.generation_context.enabled">
                        If you leave the fields blank, they will be generated.
                    </v-alert>
                    <v-alert color="muted" variant="text">
                        You will be able to add more details to the character after creation.
                    </v-alert>
                </v-col>
            </v-row>
        </v-card-text>

        <v-card-actions>
            <ConfirmActionInline :disabled="busy" action-label="Discard new character" confirm-label="Confirm" @confirm="cancel">Discard new character</ConfirmActionInline>
            <v-spacer></v-spacer>
            <v-btn color="primary" @click="createCharacter" :disabled="(!character.name && !character.generation_context.enabled) || busy">Create Character</v-btn>
        </v-card-actions>

        <p v-if="busy">
            <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
        </p>
    </v-card>
</template>

<script>

import ConfirmActionInline from './ConfirmActionInline.vue';
import WorldStateManagerTemplateApplicator from './WorldStateManagerTemplateApplicator.vue';

export default {
    name: "WorldStateManagerCharacterCreator",
    components: {
        ConfirmActionInline,
        WorldStateManagerTemplateApplicator,
    },
    props: {
        scene: Object,
        templates: Object,
        generationOptions: Object,
    },
    emits:[
        'character-created',
        'cancelled'
    ],
    data() {
        return {
            descriptionBusy: false,
            busy: false,
            character: {
                generation_context: {
                    enabled: true,
                    instructions: "",
                    generateAttributes: true,
                },
                description: "",
                name: "",
                templates: [],
                is_player: false,
            },
        }
    },
    inject: [
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'getWebsocket',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    computed: {
        characterTemplateCount() {
            if(!this.character || !this.character.templates) {
                return 0;
            }
            return this.character.templates.length;
        },
        canBePlayer() {
            return !(this.scene?.data?.explicit_player_character);
        },
    },
    methods: {
        validateTemplate(template) {
            const valid_types = ['character_attribute', 'character_detail', 'state_reinforcement'];
            if(!valid_types.includes(template.template_type)) {
                return false;
            }
            return true;
        },

        cancel() {
            if (this.character && typeof this.character.cancel === 'function') {
                this.character.cancel();
            }
            this.$emit('cancelled');
        },

        reset() {
            this.character = {
                generation_context: {
                    enabled: true,
                    instructions: "",
                    generateAttributes: true,
                },
                description: "",
                name: "",
                templates: [],
                is_player: false,
            }
        },

        sendAutocompleteRequest() {
            this.descriptionBusy = true;
            this.autocompleteRequest({
                partial: this.character.description,
                context: `character detail:description`,
                instructions: this.character.generation_context.instructions,
                character: this.character.name
            }, (completion) => {
                this.character.description += completion;
                this.descriptionBusy = false;
            }, this.$refs.description);

        },
        setCharacter(character) {
            this.character = character;
        },
        createCharacter() {
            this.busy=true;
            
            // If AI generation is disabled, use the old world_state_manager method
            if (!this.character.generation_context.enabled) {
                this.getWebsocket().send(JSON.stringify({
                    type: 'world_state_manager',
                    action: 'create_character',
                    generate: false,
                    name: this.character.name,
                    description: this.character.description,
                    is_player: this.character.is_player,
                    generate_attributes: false,
                    instructions: "",
                    generation_options: this.generationOptions,
                }));
            } else {
                // Use the new director persist_character method for AI generation
                let payload = {
                    name: this.character.name,
                    templates: this.character.templates || [],
                    active: this.character.is_player,
                    content: this.character.generation_context.instructions,
                    determine_name: this.character.generation_context.enabled && !this.character.name,
                    narrate_entry: false,
                    generate_attributes: this.character.generation_context.generateAttributes,
                    augment_attributes: "Add some additional, interesting attributes that are not already present in the character sheet.",
                    is_player: this.character.is_player,
                    description: this.character.description,
                    generation_options: this.generationOptions,
                };

                // Only include augment_attributes if enabled
                if(!payload.augment_attributes_enabled) {
                    delete payload.augment_attributes;
                }

                this.getWebsocket().send(JSON.stringify({
                    type: 'director',
                    action: 'persist_character',
                    ...payload
                }));
            }
        },
        handleMessage(message) {
            // Handle world_state_manager responses (for non-AI generation)
            if (message.type === 'world_state_manager' && message.action === 'character_created') {
                this.busy = false;
                this.$emit('character-created', message.data)
                if(this.character.created) {
                    this.character.created(message.data);
                }
                this.$emit('cancelled');
            }
            // Handle director responses (for AI generation)
            else if (message.type === 'director' && message.action === 'character_persisted') {
                this.busy = false;
                this.$emit('character-created', message.character)
                if(this.character.created) {
                    this.character.created(message.character);
                }
                this.$emit('cancelled');
            }
            else if ((message.type === 'director' || message.type === 'world_state_manager') && message.action === 'operation_done') {
                this.busy = false;
            }
            else if (message.type === 'error') {
                this.busy = false;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    },
}


</script>
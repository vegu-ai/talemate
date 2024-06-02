<template>
    <v-card>
        <v-card-text>
            <v-row>
                <v-col cols="12" lg="8" xl="6">
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
                                There already is a player character in this scene. Currently only one player character is supported. (Will change in the future.)
                            </p>
                        </v-card-text>
                    </v-card>
                </v-col>
                <v-col cols="12" lg="4" xl="3">
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

export default {
    name: "WorldStateManagerCharacterCreator",
    components: {
        ConfirmActionInline,
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
        canBePlayer() {
            return (!this.scene || !this.scene.player_character_name)
        },
    },
    methods: {

        cancel() {
            if(!this.character) {
                return;
            }

            this.character.cancel();
            this.character = {};
            this.$emit('cancelled');
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
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'create_character',
                generate: this.character.generation_context.enabled,
                name: this.character.name,
                description: this.character.description,
                is_player: this.character.is_player,
                generate_attributes: this.character.generation_context.generateAttributes,
                instructions: this.character.generation_context.instructions,
                generation_options: this.generationOptions,
            }));
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
            else if (message.action === 'character_created') {
                this.busy = false;
                this.$emit('character-created', message.data)
                this.character.created(message.data);
            }
            else if (message.action === 'operation_done') {
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
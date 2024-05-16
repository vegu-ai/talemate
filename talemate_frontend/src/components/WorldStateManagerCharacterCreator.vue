<template>
    <v-card>
        <v-card-text>


            <v-row>
                <v-col cols="6">
                    <v-card elevation="7">
                        <v-card-text>
                            <v-alert density="compact" variant="text" icon="mdi-information" color="muted" v-if="character.generationEnabled">
                                If you leave the fields blank, they will be generated.
                            </v-alert>
                            <v-text-field v-model="character.name" label="Name"></v-text-field>
        
                            <v-textarea 
                                v-model="character.description" 
                                label="Description"
                                ref="description"
                                :disabled="busy"
                                :loading="busy"
                                :hint="autocompleteInfoMessage(busy)"
                                @keyup.ctrl.enter.stop="sendAutocompleteRequest"
                                ></v-textarea>
                            <v-checkbox density="compact" :disabled="!canBePlayer" v-model="character.is_player" label="Controlled by the player"></v-checkbox>
                            <p class="text-caption text-muted" v-if="!canBePlayer">
                                There already is a player character in this scene. Currently only one player character is supported. (May change in the future.)
                            </p>
                        </v-card-text>
                    </v-card>
                </v-col>
                <v-col cols="6">
                    <v-checkbox v-model="character.generationEnabled" label="Enable AI Generation"></v-checkbox>
                    <div v-if="character.generationEnabled">
                        <v-textarea v-if="character.generationEnabled" v-model="character.generationInstructions" label="AI Generation Instructions" auto-grow rows="3" placeholder="A young man ..." hint="Briefly describe the character you want to generate.">
                        </v-textarea>
                        <v-checkbox v-model="character.generationEnabled" label="Generate Acting Instructions" messages="Will generate a set of instructions on how the character should talk and act."></v-checkbox>
                        <v-slider v-if="character.generationEnabled" v-model="character.generateDialogueExamples" label="Dialogue examples" min="0" max="10" step="1" thumb-label></v-slider>
                    </div>
                    <v-alert v-else variant="text" icon="mdi-information" color="muted">
                        You can generate a character by enabling AI generation and providing a brief description of the character you want to generate. You will also be able to manually add attributes, details, and tracked states after creation.
                    </v-alert>
                </v-col>
                <v-col cols="12" xs="12" xl="10" xxl="8">
                    <v-row v-if="character.generationEnabled">
                        <v-col cols="12" xs="12" sm="12" md="4">

                            <v-tooltip location="top" max-width="300" text="Attributes are characteristics that describe the character. They can be used to determine the character's abilities, strengths, and weaknesses.">
                                <template v-slot:activator="{ props }">
                                    <v-checkbox v-bind="props" v-model="character.generateAttributes" label="Generate Attributes"></v-checkbox>
                                </template>
                            </v-tooltip>


                            <WorldStateManagerTemplateApplicator v-if="character.generateAttributes"
                            ref="attributeTemplateSelector"
                            :select-only="true"
                            :validateTemplate="(template) => { return template.template_type === 'character_attribute' }"
                            :templates="templates"
                            :template-types="['character_attribute']"></WorldStateManagerTemplateApplicator>
                        </v-col> 
                        <v-col cols="12" xs="12" sm="12" md="4">
                            <v-tooltip location="top" max-width="300" text="Details are more detailed descriptions of certain character behaviours or information.">
                                <template v-slot:activator="{ props }">
                                    <v-checkbox v-bind="props" v-model="character.generateDetails" label="Generate Details">

                                    </v-checkbox>
                                </template>
                            </v-tooltip>
                            <WorldStateManagerTemplateApplicator v-if="character.generateDetails"
                            ref="detailTemplateSelector"
                            :select-only="true"
                            :validateTemplate="(template) => { return template.template_type === 'character_detail' }"
                            :templates="templates"
                            :template-types="['character_detail']"></WorldStateManagerTemplateApplicator>
                        </v-col> 
                        <v-col cols="12" xs="12" sm="12" md="4">
                            <v-tooltip location="top" max-width="300" text="Tracked states are states that can change over time. They can be used to track the character's health, mood, or other states using AI.">
                                <template v-slot:activator="{ props }">
                                    <v-checkbox v-bind="props" v-model="character.generateReinforcements" label="Generate Tracked States"></v-checkbox>
                                </template>
                            </v-tooltip>
                            <WorldStateManagerTemplateApplicator v-if="character.generateReinforcements"
                            ref="reinforcementTemplateSelector"
                            :select-only="true"
                            :validateTemplate="validateReinforcementTemplate"
                            :templates="templates"
                            :template-types="['state_reinforcement']"></WorldStateManagerTemplateApplicator>
                        </v-col> 
                    </v-row>
                </v-col>
            </v-row>


        </v-card-text>

        <v-card-actions>
            <ConfirmActionInline action-label="Discard new character" confirm-label="Confirm" @confirm="cancel">Discard new character</ConfirmActionInline>
        </v-card-actions>
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
    },
    watch: {
        scene: {
            immediate: true,
            handler(scene) {
                console.log({scene})
            }
        }
    },
    emits:[
        'character-created',
        'cancelled'
    ],
    data() {
        return {
            busy: false,
            character: {
                generateDialogueInstructions: true,
                generateDialogueExamples: 0,
                generationEnabled: true,
                generationInstructions: "",
                generateAttributes: true,
                generateDetails: true,
                generateReinforcements: true,
                description: "",
                name: "",
            },
        }
    },
    inject: [
        'autocompleteInfoMessage',
        'autocompleteRequest',
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
            this.busy = true;
            this.autocompleteRequest({
                partial: this.character.description,
                context: `character detail:description`,
                instructions: this.character.generationInstructions,
                character: this.character.name
            }, (completion) => {
                this.character.description += completion;
                this.busy = false;
            }, this.$refs.description);

        },
        validateReinforcementTemplate(template) {
            if (template.template_type !== 'state_reinforcement') {
                return false;
            }

            let validStateTypes = ["character"];

            if(this.character.is_player) {
                validStateTypes.push("player");
            } else{
                validStateTypes.push("npc");
            }

            if (validStateTypes.includes(template.state_type)) {
                return true;
            }

            return false;
        },

        setCharacter(character) {
            this.character = character;
        },
    }
}


</script>
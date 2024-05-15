<template>
    <v-card>
        <v-card-text>

            <v-row>
                <v-col cols="12">
                    <v-checkbox v-model="generationEnabled" label="Enable AI Generation"></v-checkbox>
                    <v-textarea v-if="generationEnabled" v-model="generationInstructions" label="AI Generation Instructions" auto-grow rows="2" placeholder="A young man ..." hint="Briefly describe the character you want to generate.">
                    </v-textarea>
                </v-col>
            </v-row>

            <v-row>
                <v-col xs="12" md="5">
                    <v-alert density="compact" variant="text" icon="mdi-information" color="muted" v-if="generationEnabled">
                        If you leave the fields blank, the AI will generate them for you.
                    </v-alert>
                    <v-text-field v-model="character.name" label="Name"></v-text-field>

                    <v-textarea v-model="character.description" label="Description"></v-textarea>
                    <v-checkbox density="compact" :disabled="!canBePlayer" v-model="character.is_player" label="Controlled by the player"></v-checkbox>
                    <p class="text-caption text-muted" v-if="!canBePlayer">
                        There already is a player character in this scene. Currently only one player character is supported. (May change in the future.)
                    </p>
                </v-col>
                <v-col xs="12" md="7">
                    <v-row v-if="generationEnabled">
                        <v-col xs="12" md="4">
                            <v-checkbox v-model="generateAttributes" label="Generate Attributes"></v-checkbox>
                            <WorldStateManagerTemplateApplicator v-if="generateAttributes"
                            ref="attributeTemplateSelector"
                            :select-only="true"
                            :validateTemplate="(template) => { return template.template_type === 'character_attribute' }"
                            :templates="templates"
                            :template-types="['character_attribute']"></WorldStateManagerTemplateApplicator>
                        </v-col> 
                        <v-col xs="12" md="4">
                            <v-checkbox v-model="generateDetails" label="Generate Details"></v-checkbox>
                            <WorldStateManagerTemplateApplicator v-if="generateDetails"
                            ref="detailTemplateSelector"
                            :select-only="true"
                            :validateTemplate="(template) => { return template.template_type === 'character_detail' }"
                            :templates="templates"
                            :template-types="['character_detail']"></WorldStateManagerTemplateApplicator>
                        </v-col> 
                        <v-col xs="12" md="4">
                            <v-checkbox v-model="generateReinforcements" label="Generate Tracked States"></v-checkbox>
                            <WorldStateManagerTemplateApplicator v-if="generateReinforcements"
                            ref="reinforcementTemplateSelector"
                            :select-only="true"
                            :validateTemplate="validateReinforcementTemplate"
                            :templates="templates"
                            :template-types="['state_reinforcement']"></WorldStateManagerTemplateApplicator>
                        </v-col> 
                    </v-row>
                    <v-row v-else>
                        <v-col cols="12">
                            <v-alert variant="text" icon="mdi-information" color="muted">
                                You can generate a character by enabling AI generation and providing a brief description of the character you want to generate. You will also be able to manually add attributes, details, and tracked states after creation.
                            </v-alert>
                        </v-col>
                    </v-row>
                </v-col>
            </v-row>


        </v-card-text>
    </v-card>
</template>

<script>

import WorldStateManagerTemplateApplicator from './WorldStateManagerTemplateApplicator.vue';

export default {
    name: "WorldStateManagerCharacterCreator",
    components: {
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
    data() {
        return {
            generationEnabled: true,
            generationInstructions: "",
            generateAttributes: true,
            generateDetails: true,
            generateReinforcements: true,
            character: {},
        }
    },
    computed: {
        canBePlayer() {
            return (!this.scene || !this.scene.player_character_name)
        },
    },
    methods: {
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
<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon variant="text">
                <v-icon>mdi-puzzle-edit</v-icon>
                <v-icon v-if="potentialNewCharactersExist()" class="btn-notification" color="warning">mdi-human-greeting</v-icon>
            </v-btn>
        </template>
        <v-list>
            <v-list-subheader>Creative Tools</v-list-subheader>
            
            <!-- deactivate active characters -->
            <v-list-item v-for="(character, index) in deactivatableCharacters" :key="character"
                @click="deactivateCharacter($event, character)">
                <template v-slot:prepend>
                    <v-icon color="secondary">mdi-exit-run</v-icon>
                </template>
                <v-list-item-title>Take out of scene: {{ character }}<v-chip variant="text" color="info" class="ml-1" size="x-small">Ctrl: no narration</v-chip></v-list-item-title>
                <v-list-item-subtitle>Make {{ character }} a passive character.</v-list-item-subtitle>
            </v-list-item>

            <!-- reactivate inactive characters -->
            <v-list-item v-for="(character, index) in inactiveCharacters" :key="character"
                @click="activateCharacter($event, character)">
                <template v-slot:prepend>
                    <v-icon color="secondary">mdi-human-greeting</v-icon>
                </template>
                <v-list-item-title>Call into scene: {{ character }}<v-chip variant="text" color="info" class="ml-1" size="x-small">Ctrl: no narration</v-chip></v-list-item-title>
                <v-list-item-subtitle>Make {{ character }} an active character.</v-list-item-subtitle>
            </v-list-item>

            <!-- persist a new character from instructions -->
            <v-list-item @click="introduceCharacterFromInstructions()">
                <template v-slot:prepend>
                    <v-icon color="highlight5">mdi-human-greeting</v-icon>
                </template>
                <v-list-item-title>Introduce new character (Directed)</v-list-item-title>
                <v-list-item-subtitle>Make a new character from instructions.</v-list-item-subtitle>
            </v-list-item>

            <!-- persist passive characters -->
            <v-list-item v-for="(character, index) in potentialNewCharacters" :key="character"
                @click="introduceCharacter($event, character)">
                <template v-slot:prepend>
                    <v-icon color="warning">mdi-human-greeting</v-icon>
                </template>
                <v-list-item-title>Introduce {{ character }}<v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Advanced</v-chip></v-list-item-title>
                <v-list-item-subtitle>Make {{ character }} an active character.</v-list-item-subtitle>
            </v-list-item>

            <!-- static tools -->
            <v-list-item v-for="(option, index) in creativeGameMenuFiltered" :key="index"
                @click="handleCreativeTool(option.value)"
                :prepend-icon="option.icon">
                <v-list-item-title>{{ option.title }}</v-list-item-title>
                <v-list-item-subtitle>{{ option.description }}</v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>


    <v-dialog v-model="dialogIntroduceCharacter" class="intro-character-dialog">
        <v-card>
            <v-card-title>
                <div v-if="newIntroduction.name">
                    Make <span class="text-primary">{{ newIntroduction.name }}</span> a permanent character.
                </div>
                <div v-else>
                    Make a new character.
                </div>
            </v-card-title>
            <v-card-text>

                <v-row>
                    <v-col cols="5">
                        <div class="text-caption text-uppercase text-muted"><v-icon>mdi-cube-scan</v-icon> Templates ({{ introduceCharacterTemplateCount }})</div>
                        <WorldStateManagerTemplateApplicator
                            ref="templateApplicator"
                            :validateTemplate="validateTemplate"
                            :templates="worldStateTemplates"
                            source="scene_tools_creative"
                            :select-only="true"
                            :template-types="['character_attribute', 'character_detail', 'state_reinforcement']"
                            @selected="(templates) => { newIntroduction.templates = templates; console.log('TEMPLATES', templates) }"/>

                    </v-col>
                    <v-col cols="7">
                        <div class="text-caption text-uppercase text-muted"><v-icon>mdi-cog</v-icon> Options</div>
                        <v-row>
                            <v-col cols="4">
                                <v-checkbox v-model="newIntroduction.determine_name" label="Determine name" color="primary" hint="Try to determine an explicit name for the character."></v-checkbox>
                            </v-col>
                            <v-col cols="4">    
                                <v-checkbox v-model="newIntroduction.active" label="Active" color="primary" hint="Make the character an active participant in the scene."></v-checkbox>
                            </v-col>
                            <v-col cols="4" v-if="newIntroduction.active">
                                <v-checkbox v-model="newIntroduction.narrate_entry" label="Narrate entry" color="primary" hint="Narrate the character's entry into the scene."></v-checkbox>
                            </v-col>
                        </v-row>
                        <v-row v-if="!newIntroduction.name">
                            <v-col cols="12">
                                <v-textarea v-model="newIntroduction.content" label="Instructions for the new character. If you have a name in mind, mention it here." rows="4" auto-grow hide-details></v-textarea>
                            </v-col>
                        </v-row>
                        <v-row v-if="newIntroduction.narrate_entry && newIntroduction.active">
                            <v-col cols="12">
                                <!-- narration direction -->
                                <v-textarea v-model="newIntroduction.narrate_entry_direction" :label="`Narration direction for ${newIntroduction.name || 'the character'}\'s entry into the scene`" rows="4" auto-grow hide-details></v-textarea>
                            </v-col>
                        </v-row>
                        <v-row>
                            <v-col cols="12">
                                <v-checkbox v-if="newIntroduction.templates.length > 0" v-model="newIntroduction.augment_attributes_enabled" label="Augment attributes" color="primary" messages="If your template selection includes character attributes, then this option will augment the character sheet with some additional attributes that are not already present."></v-checkbox>
                                <v-textarea v-if="newIntroduction.augment_attributes_enabled" v-model="newIntroduction.augment_attributes" label="Augmentation instructions" class="mt-2" rows="2" auto-grow></v-textarea>
                            </v-col>
                        </v-row>

                    </v-col>
                </v-row>


            </v-card-text>

            <v-card-actions>
                <v-btn @click="dialogIntroduceCharacter = false" color="cancel" prepend-icon="mdi-close">Cancel</v-btn>
                <v-spacer></v-spacer>
                <v-btn @click="introduceCharacter({}, newIntroduction)" color="primary" prepend-icon="mdi-human-greeting">Introduce</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>


<script>

import WorldStateManagerTemplateApplicator from './WorldStateManagerTemplateApplicator.vue';
export default {
    name: 'SceneToolsCreative',
    components: {
        WorldStateManagerTemplateApplicator,
    },
    props: {
        activeCharacters: Array,
        inactiveCharacters: Array,
        passiveCharacters: Array,
        playerCharacterName: String,
        scene: Object,
        disabled: Boolean,
        worldStateTemplates: Object,
    },
    inject: ['getWebsocket'],
    computed: {
        introduceCharacterTemplateCount() {
            if(!this.newIntroduction) {
                return 0;
            }
            return this.newIntroduction.templates.length;
        },
        deactivatableCharacters() {
            let characters = [];
            for (let character of this.activeCharacters) {
                characters.push(character);
            }
            return characters;
        },
        potentialNewCharacters() {
            // return all entries in passiveCharacters that dont exist in
            // inactiveCharacters
            let newCharacters = [];
            for (let character of this.passiveCharacters) {
                if (!this.inactiveCharacters.includes(character)) {
                    newCharacters.push(character);
                }
            }
            return newCharacters;
        },
        creativeGameMenuFiltered() {
            return this.creativeGameMenu.filter(option => {
                if (option.condition) {
                    return option.condition();
                } else {
                    return true;
                }
            });
        }
    },
    data() {
        return {
            dialogIntroduceCharacter: false,
            newIntroduction: null,
            introduction: {
                name: null,
                templates: [],
                active: true,
                content: "",
                determine_name: true,
                narrate_entry: true,
                narrate_entry_direction: "",
                augment_attributes_enabled: false,
                augment_attributes: "Add some additional, interesting attributes that are not already present in the character sheet."
            },
            creativeGameMenu: [
                {
                    "value": "setenv_creative", 
                    "title": "Node Editor", 
                    "icon": "mdi-puzzle-edit",
                    "description": "Switch to node editor",
                    "condition": () => { return this.isEnvironment('scene') }
                },
                {
                    "value": "setenv_scene", 
                    "title": "Exit Node Editor", 
                    "icon": "mdi-gamepad-square",
                    "description": "Switch to game mode",
                    "condition": () => { return this.isEnvironment('creative') }
                }
            ],
        }
    },
    methods: {
        potentialNewCharactersExist() {
            return this.potentialNewCharacters.length > 0;
        },
        
        isEnvironment(typ) {
            if(!this.scene) {
                return false;
            }
            return this.scene.environment == typ;
        },
        
        sendHotButtonMessage(message) {
            this.getWebsocket().send(JSON.stringify({ type: 'interact', text: message }));
        },

        handleCreativeTool(value) {
            if (value === "setenv_creative") {
                this.getWebsocket().send(JSON.stringify({ type: 'assistant', action: 'set_environment', environment: 'creative' }));
                return;
            }
            if (value === "setenv_scene") {
                this.getWebsocket().send(JSON.stringify({ type: 'assistant', action: 'set_environment', environment: 'scene' }));
                return;
            }
            this.sendHotButtonMessage('!' + value);
        },
        
        activateCharacter(ev, name) {
            let modifyNoNarration = ev.ctrlKey;
            this.getWebsocket().send(JSON.stringify({ type: 'director', action: 'activate_character', character_name: name, never_narrate: modifyNoNarration }));
        },

        deactivateCharacter(ev, name) {
            let modifyNoNarration = ev.ctrlKey;
            this.getWebsocket().send(JSON.stringify({ type: 'director', action: 'deactivate_character', character_name: name, never_narrate: modifyNoNarration }));
        },

        validateTemplate(template) {
            const valid_types = ['character_attribute', 'character_detail', 'state_reinforcement'];
            if(!valid_types.includes(template.template_type)) {
                return false;
            }
            return true;
        },

        showAdvancedIntroduceCharacterDialog(name) {
            this.newIntroduction = {...this.introduction};
            this.newIntroduction.name = name;
            this.dialogIntroduceCharacter = true;
        },

        introduceCharacterFromInstructions() {
            this.newIntroduction = {...this.introduction};
            this.newIntroduction.name = null;
            this.dialogIntroduceCharacter = true;
        },

        introduceCharacter(ev, name) {
            let advanced = ev.ctrlKey;
            let payload = {};

            if(typeof name === 'string' && !advanced) {
                payload = { name: name, content: " " };
            } else if(typeof name === 'string' && advanced) {
                return this.showAdvancedIntroduceCharacterDialog(name);
            } else if(typeof name === 'object') {
                payload = name;
            }

            if(!payload.name) {
                payload.name = "new character";
            }
            
            // only send augmentation instructions if augment_attributes_enabled is true
            if(!payload.augment_attributes_enabled) {
                delete payload.augment_attributes;
            }

            if(!payload) {
                return;
            }

            console.log('PAYLOAD', payload);

            this.dialogIntroduceCharacter = false;

            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'director',
                    action: 'persist_character',
                    ...payload
                }
            ));
        }
    }
}
</script>
<style scoped>
.btn-notification {
    position: absolute;
    top: 0px;
    right: 0px;
    font-size: 15px;
    border-radius: 50%;
    width: 20px;
    height: 20px;
    display: flex;
    justify-content: center;
    align-items: center;
}

.intro-character-dialog {
    max-width: 1200px;
}
</style>
<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-progress-circular class="ml-1 mr-1" size="24" v-if="agentStatus.visual && agentStatus.visual.busy" indeterminate="disable-shrink"
            color="secondary"></v-progress-circular>   
            <v-btn v-else class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon variant="text">
                <v-icon>mdi-image-frame</v-icon>
            </v-btn>
        </template>
        <v-list>
            <v-list-subheader>
                Visualize
                <span v-if="visualAgentReady">
                    <v-chip variant="tonal" label color="highlight5" class="ml-1" size="x-small"><strong class="mr-1">ALT:</strong> Prompt Only</v-chip>
                    <v-chip variant="tonal" label color="highlight5" class="ml-1" size="x-small"><strong class="mr-1">CTRL:</strong> Instructions</v-chip>
                </span>
            </v-list-subheader>
            <!-- auto attach assets checkbox -->
            <v-list-item>
                <v-checkbox 
                    v-model="autoAttachAssets" 
                    @update:model-value="toggleAutoAttachAssets"
                    label="Auto-attach visuals" 
                    color="primary"
                    density="compact"
                    hide-details
                ></v-checkbox>
            </v-list-item>
            <v-divider></v-divider>
            <!-- visual agent not ready -->
            <div v-if="!visualAgentReady">
                <v-alert type="warning" density="compact" variant="text" class="mb-3 text-caption">Visual agent is not ready for image generation, will output prompt instead.</v-alert>
            </div>
            <!-- environment -->
            <v-list-item @click="(event) => handleVisualize(null, event, VIS_TYPE.SCENE_CARD)" prepend-icon="mdi-image-filter-hdr">
                <v-list-item-title>Visualize Scene (Card)</v-list-item-title>
                <v-list-item-subtitle>Generate a cover image of the scene</v-list-item-subtitle>
            </v-list-item>
            <v-list-item @click="(event) => handleVisualize(null, event, VIS_TYPE.SCENE_BACKGROUND)" prepend-icon="mdi-image-filter-hdr">
                <v-list-item-title>Visualize Scene (Background)</v-list-item-title>
                <v-list-item-subtitle>Generate a purely environmental image of the scene</v-list-item-subtitle>
            </v-list-item>
            <!-- character submenus -->
            <v-menu v-for="character_name in characters" :key="character_name" open-on-hover location="end">
                <template v-slot:activator="{ props }">
                    <v-list-item v-bind="props" @click.stop :prepend-icon="character_name === playerCharacter ? 'mdi-account-tie' : 'mdi-account'" append-icon="mdi-chevron-right">
                        <v-list-item-title>{{ character_name }}</v-list-item-title>
                    </v-list-item>
                </template>
                <v-list>
                    <v-list-item @click="(event) => handleVisualize(character_name, event, VIS_TYPE.CHARACTER_CARD)" prepend-icon="mdi-brush">
                        <v-list-item-title>Card</v-list-item-title>
                        <v-list-item-subtitle>Generate a cover image portrait</v-list-item-subtitle>
                    </v-list-item>
                    <v-list-item @click="(event) => handleVisualize(character_name, event, VIS_TYPE.CHARACTER_PORTRAIT)" prepend-icon="mdi-brush">
                        <v-list-item-title>Portrait</v-list-item-title>
                        <v-list-item-subtitle>Generate an image of {{ character_name }}'s face</v-list-item-subtitle>
                    </v-list-item>
                </v-list>
            </v-menu>
            <!-- scene illustration -->
            <v-list-item @click="(event) => handleVisualize(null, event, VIS_TYPE.SCENE_ILLUSTRATION)" prepend-icon="mdi-image-filter-hdr">
                <v-list-item-title>Visualize Moment (Illustration)</v-list-item-title>
                <v-list-item-subtitle>Generate an image of the current moment</v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>
    
    <v-dialog v-model="dialogOpen" max-width="600">
        <v-card>
            <v-card-title>
                {{ dialogTitle }}
                <v-chip v-if="dialogPromptOnly" variant="text" color="warning" class="ml-2" size="small">Prompt Only Mode</v-chip>
            </v-card-title>
            <v-card-text>
                <v-textarea
                    v-model="instructions"
                    label="Additional Instructions"
                    hint="Enter any additional instructions for image generation"
                    rows="4"
                    auto-grow
                ></v-textarea>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn text @click="dialogOpen = false">Cancel</v-btn>
                <v-btn color="primary" @click="submitDialog">Generate</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>
<script>
import { VIS_TYPE, VIS_TYPE_OPTIONS } from '@/constants/visual';
import { isPrimaryModifier } from '@/utils/keyboardModifiers';
export default {
    name: 'SceneToolsVisual',
    props: {
        agentStatus: {
            type: Object,
            required: true,
        },
        disabled: {
            type: Boolean,
            required: true,
        },
        visualAgentReady: {
            type: Boolean,
            required: true,
        },
        npcCharacters: {
            type: Array,
            required: true,
        },
        playerCharacter: {
            type: String,
            default: null,
        }
    },

    computed: {
        characters() {
            const chars = [];
            if (this.playerCharacter) {
                chars.push(this.playerCharacter);
            }
            if (this.npcCharacters) {
                for (const npc of this.npcCharacters) {
                    if (!chars.includes(npc)) {
                        chars.push(npc);
                    }
                }
            }
            return chars;
        }
    },

    data() {
        return {
            dialogOpen: false,
            dialogTitle: '',
            dialogPromptOnly: false,
            dialogCharacterName: null,
            dialogVisType: VIS_TYPE.CHARACTER_CARD,
            instructions: '',
            autoAttachAssets: true,
            VIS_TYPE,
        }
    },

    inject: ['getWebsocket', 'appConfig'],
    
    watch: {
        appConfig: {
            handler: function(newVal) {
                if (newVal && newVal.appearance && newVal.appearance.scene) {
                    this.autoAttachAssets = newVal.appearance.scene.auto_attach_assets !== undefined 
                        ? newVal.appearance.scene.auto_attach_assets 
                        : true;
                }
            },
            deep: true,
            immediate: true,
        },
    },

    methods: {
        toggleAutoAttachAssets() {
            this.getWebsocket().send(JSON.stringify({
                type: 'quick_settings',
                action: 'set',
                setting: 'auto_attach_assets',
                value: this.autoAttachAssets
            }));
        },
        getDefaultInstructions(character_name, vis_type) {
            // Generate default instructions based on visualization type
            if (!character_name) {
                return null;
            }
            
            if (vis_type === VIS_TYPE.CHARACTER_CARD || vis_type === VIS_TYPE.CHARACTER_PORTRAIT) {
                return `A visual of ${character_name} in the current moment`;
            }
            
            return null;
        },
        handleVisualize(character_name, event, vis_type = VIS_TYPE.CHARACTER_CARD) {
            const ctrlPressed = isPrimaryModifier(event);
            const altPressed = event.altKey;
            
            if (ctrlPressed) {
                this.dialogCharacterName = character_name;
                this.dialogTitle = character_name ? `Visualize ${character_name}` : 'Visualize Environment';
                this.dialogPromptOnly = altPressed;
                this.instructions = '';
                this.dialogVisType = vis_type;
                this.dialogOpen = true;
            } else {
                this.generateImage(character_name, altPressed, null, vis_type);
            }
        },
        submitDialog() {
            this.generateImage(this.dialogCharacterName, this.dialogPromptOnly, this.instructions, this.dialogVisType);
            this.dialogOpen = false;
        },
        generateImage(character_name, prompt_only = false, instructions = null, vis_type = VIS_TYPE.CHARACTER_CARD) {
            const payload = {
                type: 'visual',
                action: 'visualize',
                vis_type: vis_type,
                prompt_only: (!this.visualAgentReady || prompt_only),
                // TODO: configurable?
                save_asset: true,
                asset_allow_override: true,
                asset_allow_auto_attach: true,
            };
            if (character_name) {
                payload.character_name = character_name;
            }
            
            // If no instructions provided, use default
            if (!instructions) {
                instructions = this.getDefaultInstructions(character_name, vis_type);
            }
            
            if (instructions) {
                payload.instructions = instructions;
            }
            this.getWebsocket().send(JSON.stringify(payload));
        },
    }
}
</script>
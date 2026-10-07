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
            <v-list-item
                v-for="row in generationRows"
                :key="row.key"
                density="compact"
                :class="row.child ? 'pl-10' : null"
                :data-testid="`auto-generation-${row.key}`"
            >
                <div class="d-flex align-center">
                    <!-- stop: a toggle keeps the menu open -->
                    <v-checkbox
                        :model-value="row.on"
                        @update:model-value="(value) => row.set(!!value)"
                        :label="row.label"
                        :disabled="!visualAgentReady"
                        color="primary"
                        density="compact"
                        hide-details
                        @click.stop
                    ></v-checkbox>
                    <v-tooltip v-if="row.overridden" text="Scene override — changes apply to this scene only" density="compact">
                        <template v-slot:activator="{ props }">
                            <v-icon v-bind="props" size="x-small" color="primary" class="ml-1">mdi-movie-open-cog-outline</v-icon>
                        </template>
                    </v-tooltip>
                    <v-spacer></v-spacer>
                    <v-tooltip :text="row.settingsLabel" density="compact">
                        <template v-slot:activator="{ props }">
                            <v-btn v-bind="props" icon="mdi-cog" size="x-small" variant="text" color="muted" class="ml-2" :aria-label="row.settingsLabel" @click="openAgentSettings(...row.settings)"></v-btn>
                        </template>
                    </v-tooltip>
                </div>
                <div v-if="row.warning" class="text-body-small text-warning d-flex align-center ms-7 mb-1">
                    <v-icon size="x-small" color="warning" class="mr-1">mdi-alert-circle-outline</v-icon>
                    {{ row.warning.text }}
                    <v-btn v-if="row.warning.settings" size="x-small" variant="text" color="warning" class="ml-1" @click="openAgentSettings(...row.warning.settings)">Settings</v-btn>
                </div>
            </v-list-item>
            <v-divider></v-divider>
            <!-- visual agent not ready -->
            <div v-if="!visualAgentReady">
                <v-alert type="warning" density="compact" variant="text" class="mb-3 text-body-small">Visual agent is not ready for image generation, will output prompt instead.</v-alert>
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

            <SceneToolsShortcutItems
                section="visual"
                :catalog="shortcutCatalog"
                :shortcuts="shortcuts"
                :templates="shortcutTemplates"
                :characters="characters"
                :disabled="disabled"
                @run="runShortcut"
                @edit="(shortcut) => $emit('shortcut-edit', shortcut)"
                @add="(section) => $emit('shortcut-add', section)"
                @add-template="(template) => $emit('shortcut-add-template', template)"
            />
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
import {
    automaticGenerationState,
    generationState,
    generationValues,
    portraitsNeedGenerateVisuals,
} from '@/utils/visualAutoGeneration';
import SceneToolsShortcutItems from './SceneToolsShortcutItems.vue';
export default {
    name: 'SceneToolsVisual',
    components: {
        SceneToolsShortcutItems,
    },
    emits: ['shortcut-add', 'shortcut-edit', 'shortcut-add-template'],
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
        },
        shortcutCatalog: {
            type: Array,
            default: () => [],
        },
        shortcuts: {
            type: Object,
            default: () => ({}),
        },
        shortcutTemplates: {
            type: Object,
            default: () => ({}),
        },
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
        },
        generationRows() {
            const automatic = automaticGenerationState(this.drawerAgent('visual'));
            if (!automatic) return [];
            const rows = [{
                key: 'automatic',
                label: 'Automatic generation',
                ...automatic,
                set: (on) => this.applyAgentValues('visual', '_config', { config: { automatic_generation: on } }),
                settings: ['visual', '_config'],
                settingsLabel: 'Visualizer settings',
            }];
            if (!automatic.on) return rows;
            const worldState = this.drawerAgent('world_state');
            const portraits = generationState(worldState, 'avatars');
            if (portraits) {
                rows.push({
                    key: 'portraits',
                    label: 'Character portraits',
                    child: true,
                    ...portraits,
                    set: (on) => this.setGeneration('avatars', portraits, 'Character portraits', on),
                    settings: ['world_state', 'avatars'],
                    settingsLabel: 'Character portrait settings',
                    warning: portraits.on && portraitsNeedGenerateVisuals(this.drawerAgent('director'))
                        ? { text: 'Needs Director Generate Visuals', settings: ['director', 'character_management'] }
                        : null,
                });
            }
            const backgrounds = generationState(worldState, 'backgrounds');
            if (backgrounds) {
                rows.push({
                    key: 'backgrounds',
                    label: 'Backgrounds',
                    child: true,
                    ...backgrounds,
                    set: (on) => this.setGeneration('backgrounds', backgrounds, 'Backgrounds', on),
                    settings: ['world_state', 'backgrounds'],
                    settingsLabel: 'Background settings',
                });
            }
            return rows;
        },
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

    inject: ['getWebsocket', 'appConfig', 'applyAgentValues', 'applySceneAgentValues', 'openAgentSettings', 'getAgents'],
    
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
        // The drawer's copy holds values a save in flight wrote, which a stale
        // status frame cannot put back; agentStatus is read for reactivity and
        // as the fallback before the drawer has the agent.
        drawerAgent(name) {
            const status = this.agentStatus[name];
            const agent = this.getAgents().find((candidate) => candidate.name === name);
            if (!agent) return status;
            return { actions: agent.actions, scene_overrides: agent.data?.scene_overrides };
        },
        // The row's override mark promises a scene-only change, so both fields of
        // the pair go to the scene, the one not overridden yet included.
        setGeneration(actionKey, state, label, on) {
            const values = generationValues(this.drawerAgent('world_state'), actionKey, on);
            if (state.overridden) {
                this.applySceneAgentValues([{ agent: 'world_state', action: actionKey, config: values.config }], `${label}: ${on ? 'On' : 'Off'}`);
                return;
            }
            this.applyAgentValues('world_state', actionKey, values);
        },
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
        runShortcut({shortcut, entry, character}) {
            switch (entry.id) {
                case 'visual.visualize_environment_card':
                    this.generateImage(null, false, shortcut.instructions, VIS_TYPE.SCENE_CARD);
                    break;
                case 'visual.visualize_environment_background':
                    this.generateImage(null, false, shortcut.instructions, VIS_TYPE.SCENE_BACKGROUND);
                    break;
                case 'visual.visualize_character_card':
                    this.generateImage(character, false, shortcut.instructions, VIS_TYPE.CHARACTER_CARD);
                    break;
                case 'visual.visualize_character_portrait':
                    this.generateImage(character, false, shortcut.instructions, VIS_TYPE.CHARACTER_PORTRAIT);
                    break;
                default:
                    console.warn('unhandled scene tool shortcut action', entry.id);
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
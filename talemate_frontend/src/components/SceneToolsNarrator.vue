<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon variant="text">
                <v-icon>mdi-script-text</v-icon>
            </v-btn>
        </template>
        <v-list>
            <v-list-subheader>Narrator Actions</v-list-subheader>

            <!-- NEW (defined in template) -->

            <!-- Progress Story -->
            <v-list-item 
                density="compact"
                @click="actionProgress" 
                prepend-icon="mdi-script-text-play"
            >
                <v-list-item-title>Progress Story <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">{{ primaryModifierLabel }}: Provide direction</v-chip></v-list-item-title>
                <v-btn @click.stop="(e) => { actionProgress(e, PROGRESS_SHORTCUT_MINOR) }" variant="tonal" color="highlight2" class="mr-1" size="x-small" :prepend-icon="'mdi-dice-multiple'">Minor</v-btn>
                <v-btn @click.stop="(e) => { actionProgress(e, PROGRESS_SHORTCUT_MAJOR) }" variant="tonal" color="highlight2" class="mr-1" size="x-small" :prepend-icon="'mdi-dice-multiple'">Major</v-btn>
                <v-btn @click.stop="(e) => { actionProgress(e, PROGRESS_SHORTCUT_CURVEBALL) }" variant="tonal" color="highlight2" size="x-small" :prepend-icon="'mdi-dice-multiple'">Curveball</v-btn>
            </v-list-item>

            <!-- Environment -->
            <v-list-item 
                density="compact"
                @click="actionNarrateEnvironment" 
                prepend-icon="mdi-waves"
            >
                <v-list-item-title>Narrate Environment <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">{{ primaryModifierLabel }}: Provide direction</v-chip></v-list-item-title>
            </v-list-item>

            <!-- Look at Scene -->
            <v-list-item 
                density="compact"
                @click="actionLookAtScene" 
                prepend-icon="mdi-image-filter-hdr"
            >
                <v-list-item-title>Look at Scene <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">{{ primaryModifierLabel }}: Provide direction</v-chip></v-list-item-title>
            </v-list-item>

            <!-- Look at NPCs -->
            <v-list-item 
                v-for="(npc_name, index) in npcCharacters" 
                :key="index"
                @click="(ev) => { actionLookAtCharacter(ev, null, {character: npc_name}) }" 
                prepend-icon="mdi-account-eye"
            >
                <v-list-item-title>Look at {{ npc_name }} <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">{{ primaryModifierLabel }}: Provide direction</v-chip></v-list-item-title>
            </v-list-item>

            <!-- Query -->
            <v-list-item 
                density="compact"
                @click="() => { actionQuery() }" 
                prepend-icon="mdi-crystal-ball"
            >
                <v-list-item-title>Query</v-list-item-title>
                <v-list-item-subtitle>Ask a question or give a task to the narrator</v-list-item-subtitle>
            </v-list-item>

            <SceneToolsShortcutItems
                section="narrator"
                :catalog="shortcutCatalog"
                :shortcuts="shortcuts"
                :characters="npcCharacters"
                :disabled="disabled"
                @run="runShortcut"
                @edit="(shortcut) => $emit('shortcut-edit', shortcut)"
                @add="(section) => $emit('shortcut-add', section)"
            />
        </v-list>
    </v-menu>

    <!-- request input for query action -->
    <RequestInput ref="actionQueryInput" title="Narrator Query"
        :instructions="'Ask a question or give a task to the narrator.\n\nThis is not a permanent instruction.'"
        input-type="multiline" icon="mdi-crystal-ball" :size="750" @continue="actionQuery" />

    <!-- narrative direction input -->
    <RequestInput ref="narrativeDirectionInput" title="Narrator Prompt"
        :instructions="'Prompt direction - provide an instruction for the narrator to follow for this action'"
        input-type="multiline" icon="mdi-script-text-play" :size="750" @continue="applyDirection" placeholder="Slightly move the story forward." />

</template>

<script>
import RequestInput from './RequestInput.vue';
import SceneToolsShortcutItems from './SceneToolsShortcutItems.vue';
import { isPrimaryModifier, primaryModifierLabel } from '@/utils/keyboardModifiers';

const PROGRESS_SHORTCUT_MINOR = "Introduce a minor change to the story.";
const PROGRESS_SHORTCUT_MAJOR = "Introduce a major shift in the story.";
const PROGRESS_SHORTCUT_CURVEBALL = "Introduce a major curveball in the story. Time to get crazy!";

export default {
    name: "SceneToolsNarrator",
    components: {
        RequestInput,
        SceneToolsShortcutItems,
    },
    props: {
        npcCharacters: Array,
        disabled: Boolean,
        shortcutCatalog: {
            type: Array,
            default: () => [],
        },
        shortcuts: {
            type: Object,
            default: () => ({}),
        },
    },
    inject: ['getWebsocket'],
    emits: ['shortcut-add', 'shortcut-edit'],
    data() {
        return {
            PROGRESS_SHORTCUT_MINOR,
            PROGRESS_SHORTCUT_MAJOR,
            PROGRESS_SHORTCUT_CURVEBALL,
            primaryModifierLabel,
        }
    },
    methods: {

        requestDirection(params) {
            this.$nextTick(() => {
                this.$refs.narrativeDirectionInput.openDialog(params);
            });
        },

        applyDirection(input, params){
            let callback = this[`action${params.action}`];
            if(callback){
                callback({}, input, params);
            }
        },

        runShortcut({shortcut, entry, character}) {
            switch (entry.id) {
                case 'narrator.progress':
                    this.actionProgress({}, shortcut.instructions);
                    break;
                case 'narrator.narrate_environment':
                    this.actionNarrateEnvironment({}, shortcut.instructions);
                    break;
                case 'narrator.look_at_scene':
                    this.actionLookAtScene({}, shortcut.instructions);
                    break;
                case 'narrator.look_at_character':
                    this.actionLookAtCharacter({}, shortcut.instructions, {character});
                    break;
                default:
                    console.warn('unhandled scene tool shortcut action', entry.id);
            }
        },

        // Narrator actions

        /**
         * Send a message to the narrator to query something or give a one-time instruction.
         * @method actionQuery
         * @param {string} input - The query or instruction to send to the narrator. If not provided, open the dialog.
         */

        actionQuery(input) {

            if (!input) {
                this.$refs.actionQueryInput.openDialog();
                return;
            }

            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'narrator',
                    action: 'query',
                    query: input,
                }
            ));

        },

        /**
         * Progress the story
         * @method actionProgress
         * @param {string} narrativeDirection - The direction to progress the story in
         */

        actionProgress(ev, narrativeDirection="") {

            if (isPrimaryModifier(ev)) {
                this.requestDirection({action: 'Progress', input: narrativeDirection});
                return;
            }

            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'narrator',
                    action: 'progress',
                    narrative_direction: narrativeDirection || "",
                }
            ));
        },

        /**
         * Narrate the environment
         * @method actionNarrateEnvironment
         * @param {string} narrativeDirection - The direction to narrate the environment in
         */

        actionNarrateEnvironment(ev, narrativeDirection="") {

            if (isPrimaryModifier(ev)) {
                this.requestDirection({action: 'NarrateEnvironment'});
                return;
            }

            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'narrator',
                    action: 'narrate_environment',
                    narrative_direction: narrativeDirection || "",
                }
            ));

        },

        /**
         * Look at the scene
         * @method actionLookAtScene
         * @param {string} narrativeDirection - The direction to narrate the scene in
         */

        actionLookAtScene(ev, narrativeDirection="") {

            if (isPrimaryModifier(ev)) {
                this.requestDirection({action: 'LookAtScene'});
                return;
            }

            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'narrator',
                    action: 'look_at_scene',
                    narrative_direction: narrativeDirection || "",
                }
            ));
        },

        /**
         * Look at a character
         * @method actionLookAtCharacter
         * @param {string} character - The character to look at
         * @param {string} narrativeDirection - The direction to narrate the character in
         */

        actionLookAtCharacter(ev, narrativeDirection="", params) {

            if (isPrimaryModifier(ev)) {
                this.requestDirection({action: 'LookAtCharacter', ...params});
                return;
            }

            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'narrator',
                    action: 'look_at_character',
                    character: params.character,
                    narrative_direction: narrativeDirection || "",
                }
            ));
        },


    }
}

</script>
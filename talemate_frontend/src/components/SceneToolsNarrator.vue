<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon>
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
                <v-list-item-title>Progress Story <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Provide direction</v-chip></v-list-item-title>
            </v-list-item>

            <!-- Environment -->
            <v-list-item 
                density="compact"
                @click="actionNarrateEnvironment" 
                prepend-icon="mdi-waves"
            >
                <v-list-item-title>Narrate Environment <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Provide direction</v-chip></v-list-item-title>
            </v-list-item>

            <!-- Look at Scene -->
            <v-list-item 
                density="compact"
                @click="actionLookAtScene" 
                prepend-icon="mdi-image-filter-hdr"
            >
                <v-list-item-title>Look at Scene <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Provide direction</v-chip></v-list-item-title>
            </v-list-item>

            <!-- Look at NPCs -->
            <v-list-item 
                v-for="(npc_name, index) in npcCharacters" 
                :key="index"
                @click="(ev) => { actionLookAtCharacter(ev, null, {character: npc_name}) }" 
                prepend-icon="mdi-account-eye"
            >
                <v-list-item-title>Look at {{ npc_name }} <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Provide direction</v-chip></v-list-item-title>
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
        </v-list>
    </v-menu>

    <!-- request input for query action -->
    <RequestInput ref="actionQueryInput" title="Narrator Query"
        :instructions="'Ask a question or give a task to the narrator.\n\nThis is not a permanent instruction.'"
        input-type="multiline" icon="mdi-crystal-ball" :size="750" @continue="actionQuery" />

    <!-- narrative direction input -->
    <RequestInput ref="narrativeDirectionInput" title="Narrator Prompt"
        :instructions="'Prompt direction - provide an instruction for the narrator to follow for this action'"
        input-type="multiline" icon="mdi-script-text-play" :size="750" @continue="applyDirection" />

</template>

<script>
import RequestInput from './RequestInput.vue';

export default {
    name: "SceneToolsNarrator",
    components: {
        RequestInput,
    },
    props: {
        npcCharacters: Array,
        disabled: Boolean,
    },
    inject: ['getWebsocket'],
    data() {
        return {
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

            if (ev.ctrlKey) {
                this.requestDirection({action: 'Progress'});
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

            if (ev.ctrlKey) {
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

            if (ev.ctrlKey) {
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
            
            if (ev.ctrlKey) {
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
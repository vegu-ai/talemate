<template>
    <v-menu location="top">
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-3" v-bind="props" :disabled="disabled" color="primary" icon>
                <v-icon>mdi-dice-multiple</v-icon>
            </v-btn>
        </template>
        <v-list>
            <v-list-subheader>Director Actions</v-list-subheader>
            <!-- Generate dynamic choices  -->
            <v-list-item 
                density="compact"
                @click="actionRequestDynamicChoices" 
                prepend-icon="mdi-tournament"
            >
                <v-list-item-title>Generate dynamic actions<v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Provide direction</v-chip></v-list-item-title>
            </v-list-item>

        </v-list>
    </v-menu>

    <!-- narrative direction input -->
    <RequestInput ref="instructionsInput" title="Director Prompt"
        :instructions="'Instructions - Provide an instruction for the director to follow for this action'"
        input-type="multiline" icon="mdi-dice-multiple" :size="750" @continue="applyDirection" />

</template>

<script>
import RequestInput from './RequestInput.vue';

export default {
    name: "SceneToolsDirector",
    components: {
        RequestInput,
    },
    props: {
        npcCharacters: Array,
        disabled: Boolean,
    },
    inject: ['getWebsocket'],
    data() {
        return {}
    },
    methods: {

        requestDirection(params) {
            this.$nextTick(() => {
                this.$refs.instructionsInput.openDialog(params);
            });
        },

        applyDirection(input, params){
            let callback = this[`action${params.action}`];
            if(callback){
                callback({}, input, params);
            }
        },

        // Director actions

        /**
         * Progress the story
         * @method actionRequestDynamicChoices
         * @param {string} instructions - The direction to progress the story in
         */

        actionRequestDynamicChoices(ev, instructions="") {

            if (ev.ctrlKey) {
                this.requestDirection({action: 'RequestDynamicChoices'});
                return;
            }

            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'director',
                    action: 'request_dynamic_choices',
                    instructions: instructions || "",
                }
            ));
        },
    }
}

</script>
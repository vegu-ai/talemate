<template>
    <v-menu>
        <template v-slot:activator="{ props }">
            <v-btn class="hotkey mx-1" v-bind="props" :disabled="disabled" color="primary" icon variant="text">
                <v-icon>mdi-account-voice</v-icon>
            </v-btn>
        </template>
        <v-list density="compact">
            <v-list-subheader>Actor Actions</v-list-subheader>
            <v-list-item v-for="npcName in npcCharacters" :key="npcName"
                @click="(ev) => { actionGenerateActingAction(ev, null, {character: npcName}) }" prepend-icon="mdi-comment-account-outline">
                <v-list-item-title>Actor Action ({{ npcName }})</v-list-item-title>
                <v-list-item-subtitle>Generate Actor Action <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Provide direction</v-chip></v-list-item-subtitle>
            </v-list-item>

            <v-list-item @click="actionGenerateActingAction" prepend-icon="mdi-comment-text-outline">
                <v-list-item-title>Actor Action</v-list-item-title>
                <v-list-item-subtitle>Generate Actor Action <v-chip variant="text" color="highlight5" class="ml-1" size="x-small">Ctrl: Provide direction</v-chip></v-list-item-subtitle>
            </v-list-item>
        </v-list>
    </v-menu>

    <!-- acting direction input -->
    <RequestInput ref="actingDirectionInput" title="Actor Prompt"
        instructions="Prompt direction - give instructions to the actor. They should be written as if talking to the actor. For example, 'Take a step back and look around the room.'"
        input-type="multiline" icon="mdi-bullhorn" :size="750" @continue="applyDirection" />

</template>

<script>
import RequestInput from './RequestInput.vue';

export default {
    name: "SceneToolsActor",
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
                this.$refs.actingDirectionInput.openDialog(params);
            });
        },

        applyDirection(input, params){
            let callback = this[`action${params.action}`];
            if(callback){
                callback({}, input, params);
            }
        },

        // Actor actions

        /**
         * Generate actor action
         * @method actionGenerateActingAction
         * @param {string} actingDirection - The direction to give to the actor
         */

        actionGenerateActingAction(ev, actingDirection="", params) {

            if (ev.ctrlKey) {
                this.requestDirection({action: 'GenerateActingAction', ...params});
                return;
            }
            this.getWebsocket().send(JSON.stringify(
                {
                    type: 'conversation',
                    action: 'request_actor_action',
                    instructions: actingDirection || "",
                    instructions_through_director: true,
                    character: params ? params.character : "",
                }
            ));
        },
    }
}

</script>
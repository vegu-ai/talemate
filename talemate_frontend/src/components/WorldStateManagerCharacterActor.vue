
<template>
    <v-row>
        <v-col cols="3">
            <v-tabs density="compact" color="indigo-lighten-3" direction="vertical" v-model="tab">
                <v-tab value="instructions" class="text-caption">
                    Dialogue Instructions
                </v-tab>
                <v-tab value="examples" class="text-caption" disabled>
                    Dialogue Examples
                </v-tab>
            </v-tabs>
        </v-col>
        <v-col cols="9">

            <div v-if="tab == 'instructions'">
                <v-textarea 
                placeholder="speak less formally, sitcom type dialogue" 
                v-model="dialogueInstructions" label="Dialogue Instructions" 
                :color="dialogueInstructionsDirty ? 'primary' : null"
                @update:model-value="queueUpdateCharacterActor"
                rows="3" 
                auto-grow></v-textarea>
                <v-alert icon="mdi-bullhorn" density="compact" variant="text" color="grey">
                    <p>
                        Any instructions you enter here will be inserted into the context right before
                        <span class="text-primary">{{ character.name }}</span> speaks their next line. It can have a strong effect on the style
                        of the dialogue. Use this when a character has trouble sticking to their
                        personality / type of speech. Try to keep it short and write them as if giving 
                        instructions to an actor.
                    </p>
                    <v-divider class="mt-2 mb-2"></v-divider>
                    <p>
                        <v-icon size="small" color="warning" class="mr-1">mdi-alert</v-icon>Giving long instructions here may degrade the quality of the dialogue, especially
                        in the beginning of the conversation. 
                    </p>
                </v-alert>
            </div>

            <div v-else-if="tab == 'examples'">
            </div>

        </v-col>
    </v-row>
</template>

<script>

export default {
    name: 'WorldStateManagerCharacterActor',
    data() {
        return {
            tab: "instructions",
            dialogueInstructions: null,
            dialogueInstructionsDirty: false,
            updateCharacterActorTimeout: null,
        }
    },
    props: {
        character: Object,
    },
    inject: ['getWebsocket', 'registerMessageHandler'],
    methods: {

        queueUpdateCharacterActor() {
            this.dialogueInstructionsDirty = true;
            if (this.updateCharacterActorTimeout) {
                clearTimeout(this.updateCharacterActorTimeout);
            }
            this.updateCharacterActorTimeout = setTimeout(this.updateCharacterActor, 500);
        },
        
        updateCharacterActor() {
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "update_character_actor",
                name: this.character.name,
                dialogue_instructions: this.dialogueInstructions,
                dialogue_examples: this.character.example_dialogue,
            }));
        },
        
        handleMessage(data) {
            if(data.type === 'world_state_manager') {
                if(data.action === 'character_actor_updated') {
                    this.dialogueInstructionsDirty = false;
                }
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    mounted() {
        this.dialogueInstructions = this.character.actor.dialogue_instructions;
    },
}

</script>
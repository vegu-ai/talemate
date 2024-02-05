
<template>
    <v-row>
        <v-col cols="3">
            <v-tabs density="compact" color="indigo-lighten-3" direction="vertical" v-model="tab">
                <v-tab value="instructions" class="text-caption">
                    Dialogue Instructions
                </v-tab>
                <v-tab value="examples" class="text-caption">
                    Dialogue Examples
                </v-tab>
            </v-tabs>
        </v-col>
        <v-col cols="9">

            <div v-if="tab == 'instructions'">
                <v-textarea 
                placeholder="speak less formally, use more contractions, and be more casual." 
                v-model="dialogueInstructions" label="Acting Instructions" 
                :color="dialogueInstructionsDirty ? 'primary' : null"
                @update:model-value="queueUpdateCharacterActor"
                rows="3" 
                auto-grow></v-textarea>
                <v-alert icon="mdi-bullhorn" density="compact" variant="text" color="grey">
                    <p>
                        Any instructions you enter here will be inserted into the context right before
                        <span class="text-primary">{{ character.name }}</span> speaks the next line. It can have a strong effect on the style
                        of the dialogue. Use this when a character has trouble sticking to their
                        personality / type of speech. Try to keep it short and write them as if giving 
                        instructions to an actor.
                    </p>
                    <v-divider class="mt-2 mb-2"></v-divider>
                    <p>
                        <v-icon size="small" color="orange" class="mr-1">mdi-flask</v-icon><span class="text-orange">Experimental feature</span> - whether or not this improves or degrades generations strongly depends on LLM  used. Giving too long instructions here may degrade the quality of the dialogue, especially in the beginning of the scene. 
                    </p>
                </v-alert>
            </div>

            <div v-else-if="tab == 'examples'">
                <ContextualGenerate 
                    :context="'character dialogue:'" 
                    :character="character.name"
                    :rewrite-enabled="false"
                    @generate="content => { dialogueExamples.push(content); queueUpdateCharacterActor(); }"
                />
                <v-text-field v-model="dialogueExample" label="Add Dialogue Example" @keyup.enter="dialogueExamples.push(dialogueExample); dialogueExample = ''; queueUpdateCharacterActor();" dense></v-text-field>
                <v-list density="compact" nav>
                    <v-list-item v-for="(example, index) in dialogueExamplesWithNameStripped" :key="index">
                        <template v-slot:prepend>
                            <v-btn  color="red-darken-2" rounded="sm" size="x-small" icon variant="text" @click="dialogueExamples.splice(index, 1); queueUpdateCharacterActor()">
                                <v-icon>mdi-close-box-outline</v-icon>
                            </v-btn>
                        </template>
                        <div class="text-caption text-grey">
                            {{ example }}
                        </div>
                    </v-list-item>
                </v-list>
            </div>

        </v-col>
    </v-row>
</template>

<script>

import ContextualGenerate from './ContextualGenerate.vue';

export default {
    name: 'WorldStateManagerCharacterActor',
    components: {
        ContextualGenerate,
    },
    data() {
        return {
            tab: "instructions",
            dialogueExamples: [],
            dialogueExample: "",
            dialogueInstructions: null,
            dialogueInstructionsDirty: false,
            updateCharacterActorTimeout: null,
        }
    },
    computed: {
        dialogueExamplesWithNameStripped() {
            return this.dialogueExamples.map((example) => {
                return example.replace(this.character.name + ': ', '');
            });
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
                dialogue_examples: this.dialogueExamples,
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
        console.log("MOUNTED", this.character)
        this.dialogueInstructions = this.character.actor.dialogue_instructions;
        this.dialogueExamples = this.character.actor.dialogue_examples;
    },
}

</script>
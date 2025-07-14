
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
                <v-tab value="voice" class="text-caption">
                    Voice
                </v-tab>
            </v-tabs>
        </v-col>
        <v-col cols="9">


            <div v-if="tab == 'instructions'">
                <ContextualGenerate 
                    ref="contextualGenerate"
                    uid="wsm.character_acting_instructions"
                    :context="'acting_instructions:'" 
                    :character="character.name"
                    :rewrite-enabled="false"
                    :generation-options="generationOptions"
                    :specify-length="true"
                    @generate="content => { setCharacterDialogueInstructions(content); updateCharacterActor(); }"
                />
                <v-textarea 
                :loading="dialogueInstructionsBusy"
                :disabled="dialogueInstructionsBusy"
                placeholder="speak less formally, use more contractions, and be more casual." 
                v-model="dialogueInstructions" label="Acting Instructions" 
                :color="dialogueInstructionsDirty ? 'info' : null"
                @update:model-value="dialogueInstructionsDirty = true"
                @blur="updateCharacterActor(true)"
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
                    ref="contextualGenerate"
                    uid="wsm.character_dialogue"
                    :context="'character dialogue:'" 
                    :instructions-placeholder="`An example of what ${character.name} would say when...`"
                    :character="character.name"
                    :rewrite-enabled="false"
                    :generation-options="generationOptions"
                    :specify-length="true"
                    @generate="content => { dialogueExamples.push(content); updateCharacterActor(); }"
                />


                <v-text-field v-model="dialogueExample" label="Add Dialogue Example" @keyup.enter="dialogueExamples.push(dialogueExample); dialogueExample = ''; updateCharacterActor();" dense></v-text-field>
                <v-list density="compact" nav>
                    <v-list-item v-for="(example, index) in dialogueExamplesWithNameStripped" :key="index">
                        <template v-slot:prepend>
                            <v-btn  color="red-darken-2" rounded="sm" size="x-small" icon variant="text" @click="dialogueExamples.splice(index, 1); updateCharacterActor()">
                                <v-icon>mdi-close-box-outline</v-icon>
                            </v-btn>
                        </template>
                        <div class="text-caption text-grey">
                            {{ example }}
                        </div>
                    </v-list-item>
                </v-list>
            </div>
            <div v-else-if="tab == 'voice'">
                <VoiceSelect v-model="voiceId" @update:modelValue="voiceDirty = true; updateCharacterVoice();" />

                <v-btn 
                    :disabled="!voiceId || testingVoice" 
                    :loading="testingVoice"
                    variant="text"
                    color="secondary"
                    class="mt-2"
                    prepend-icon="mdi-play"
                    @click="testCharacterVoice"
                >
                    Test Voice
                </v-btn>

                <v-alert color="muted" density="compact" variant="text" class="mt-2">
                    Select a voice for <span class="text-primary">{{ character.name }}</span>. Only voices from ready TTS APIs are listed.
                </v-alert>
            </div>
        </v-col>
    </v-row>
    <SpiceAppliedNotification :uids="['wsm.character_dialogue']"></SpiceAppliedNotification>

</template>

<script>

import ContextualGenerate from './ContextualGenerate.vue';
import SpiceAppliedNotification from './SpiceAppliedNotification.vue';
import VoiceSelect from './VoiceSelect.vue';

export default {
    name: 'WorldStateManagerCharacterActor',
    components: {
        ContextualGenerate,
        SpiceAppliedNotification,
        VoiceSelect,
    },
    data() {
        return {
            tab: "instructions",
            dialogueExamples: [],
            dialogueExample: "",
            dialogueInstructions: null,
            dialogueInstructionsDirty: false,
            voiceId: null,
            voiceDirty: false,
            testingVoice: false,
            updateCharacterActorTimeout: null,
        }
    },
    computed: {
        dialogueInstructionsBusy() {
            return this.$refs.contextualGenerate && this.$refs.contextualGenerate.busy;
        },
        dialogueExamplesWithNameStripped() {
            return this.dialogueExamples.map((example) => {
                return example.replace(this.character.name + ': ', '');
            });
        },
        tooltipText() {
            return `Automatically generate dialogue instructions for ${this.character.name}, based on their attributes and description`;
        }
    },
    watch: {
        character: {
            handler() {
                this.dialogueInstructions = this.character.actor.dialogue_instructions;
                this.dialogueExamples = this.character.actor.dialogue_examples;
                this.voiceId = this.character.voice ? this.character.voice.id : null;
            },
            deep: true,
            immediate: true,
        },
    },
    props: {
        character: Object,
        templates: Object,
        generationOptions: Object,
    },
    emits: [
        'require-scene-save'
    ],
    inject: ['getWebsocket', 'registerMessageHandler'],
    methods: {
        
        updateCharacterActor(only_if_dirty = false) {

            if(only_if_dirty && !this.dialogueInstructionsDirty) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "update_character_actor",
                name: this.character.name,
                dialogue_instructions: this.dialogueInstructions,
                dialogue_examples: this.dialogueExamples,
            }));
        },

        setCharacterDialogueInstructions(instructions) {
            this.dialogueInstructions = instructions;
            this.dialogueInstructionsDirty = true;
        },

        generateCharacterDialogueInstructions() {
            this.dialogueInstructionsBusy = true;
            this.getWebsocket().send(JSON.stringify({
                type: "world_state_manager",
                action: "generate_character_dialogue_instructions",
                name: this.character.name,
            }));
        },
        
        handleMessage(data) {
            if(data.type === 'world_state_manager') {
                if(data.action === 'character_actor_updated') {
                    this.dialogueInstructionsDirty = false;
                } else if (data.action === 'character_voice_updated') {
                    this.voiceDirty = false;
                } else if (data.action === 'character_dialogue_instructions_generated') {
                    this.dialogueInstructions = data.data.instructions;
                    this.dialogueInstructionsBusy = false;
                }
            } else if (data.type === 'voice_library') {
                if (data.action === 'operation_done' || data.action === 'operation_failed') {
                    this.testingVoice = false;
                }
            }
        },

        updateCharacterVoice() {
            if(!this.voiceDirty) return;

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_voice',
                name: this.character.name,
                voice_id: this.voiceId,
            }));
        },

        testCharacterVoice() {
            if (!this.voiceId || this.testingVoice) return;

            // Extract provider and provider_id from voiceId (format: "provider:provider_id")
            const [provider, ...providerIdParts] = this.voiceId.split(':');
            const provider_id = providerIdParts.join(':');

            // Get a random dialogue example, or use default text
            let testText = "This is a test of the selected voice.";
            if (this.dialogueExamples && this.dialogueExamples.length > 0) {
                const randomIndex = Math.floor(Math.random() * this.dialogueExamples.length);
                testText = this.dialogueExamples[randomIndex];
                // Strip character name prefix if present
                if (testText.startsWith(this.character.name + ':')) {
                    testText = testText.substring(this.character.name.length + 1).trim();
                }
            }

            this.testingVoice = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'voice_library',
                action: 'test',
                provider: provider,
                provider_id: provider_id,
                text: testText,
            }));
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
    mounted() {
        this.dialogueInstructions = this.character.actor.dialogue_instructions;
        this.dialogueExamples = this.character.actor.dialogue_examples;
        this.voiceId = this.character.voice ? this.character.voice.id : null;
    },
}

</script>
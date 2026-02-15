<template>
    <v-dialog v-model="dialog" max-width="600">
        <v-card>
            <v-card-title>{{ title }}</v-card-title>
            <v-card-text>
                <v-alert v-if="description" density="compact" variant="text" color="grey" icon="mdi-information-outline" class="mb-2">
                    {{ description }}
                </v-alert>

                <v-alert v-if="character" density="compact" icon="mdi-account" variant="text" color="grey" class="mb-2">
                    {{ character }}
                </v-alert>

                <v-select
                    v-if="characters.length > 0 && !character"
                    v-model="selectedCharacter"
                    :items="characters"
                    label="Character"
                    prepend-inner-icon="mdi-account"
                ></v-select>

                <v-text-field
                    ref="questionInput"
                    v-model="question"
                    label="Question or State description"
                    hint="A question or state description that the AI will track and update."
                    :rules="[v => !!v || 'Question is required']"
                ></v-text-field>

                <v-row>
                    <v-col cols="6">
                        <v-number-input
                            v-model="interval"
                            label="Update every N turns"
                            :min="1"
                            :max="100"
                            :step="1"
                        ></v-number-input>
                    </v-col>
                    <v-col cols="6">
                        <v-select
                            v-model="insert"
                            :items="availableInsertionModes"
                            label="Context Attachment Method"
                        ></v-select>
                    </v-col>
                </v-row>

                <v-textarea
                    v-model="instructions"
                    label="Additional instructions to the AI for generating this state."
                    rows="3"
                    auto-grow
                    max-rows="5"
                ></v-textarea>

                <v-checkbox
                    v-if="effectiveCharacter"
                    v-model="requireActive"
                    label="Require character active"
                    color="primary"
                    messages="Only progress this reinforcement when the character is active in the scene."
                ></v-checkbox>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn color="primary" variant="text" prepend-icon="mdi-text-box-plus" @click="create" :disabled="!question || (characters.length > 0 && !effectiveCharacter)">Create</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
export default {
    name: 'QuickCreateStateReinforcement',
    props: {
        title: {
            type: String,
            default: 'Create State Reinforcement',
        },
        description: {
            type: String,
            default: '',
        },
        character: {
            type: String,
            default: '',
        },
        characters: {
            type: Array,
            default: () => [],
        },
        insertionModes: {
            type: Array,
            required: true,
        },
        defaultInsert: {
            type: String,
            default: 'never',
        },
        defaultInterval: {
            type: Number,
            default: 10,
        },
    },
    data() {
        return {
            dialog: false,
            question: '',
            interval: this.defaultInterval,
            insert: this.defaultInsert,
            instructions: '',
            requireActive: true,
            selectedCharacter: '',
        }
    },
    emits: ['create'],
    computed: {
        effectiveCharacter() {
            return this.character || this.selectedCharacter;
        },
        availableInsertionModes() {
            if (this.effectiveCharacter) {
                return this.insertionModes;
            }
            return this.insertionModes.filter(mode => mode.value !== 'conversation-context');
        },
    },
    methods: {
        open() {
            this.dialog = true;
            this.question = '';
            this.interval = this.defaultInterval;
            this.insert = this.defaultInsert;
            this.instructions = '';
            this.requireActive = true;
            this.selectedCharacter = '';
            this.$nextTick(() => {
                if (this.$refs.questionInput && this.$refs.questionInput.focus) {
                    this.$refs.questionInput.focus();
                }
            });
        },

        create() {
            this.$emit('create', {
                question: this.question,
                interval: this.interval,
                insert: this.insert,
                instructions: this.instructions,
                require_active: this.requireActive,
                character: this.effectiveCharacter,
            });
            this.dialog = false;
        },
    },
}
</script>

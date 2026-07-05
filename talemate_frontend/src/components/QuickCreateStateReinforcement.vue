<template>
    <v-dialog v-model="dialog" max-width="600">
        <v-card>
            <v-card-title>{{ title }}</v-card-title>
            <v-card-text>
                <v-alert v-if="description" density="compact" variant="text" color="grey" icon="mdi-information-outline" class="mb-2">
                    {{ description }}
                </v-alert>

                <v-select
                    v-if="showTargetSelector"
                    v-model="selectedTarget"
                    :items="targetItems"
                    label="Track state for"
                    prepend-inner-icon="mdi-target"
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
                <v-btn color="primary" variant="text" prepend-icon="mdi-text-box-plus" @click="create" :disabled="!question || !hasTargetSelection">Create</v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
const WORLD_TARGET = '__world__';

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
        characters: {
            type: Array,
            default: () => [],
        },
        insertionModes: {
            type: Array,
            required: true,
        },
        // When true the target selector offers "World" alongside the characters,
        // so a single modal can create either a world or a character state.
        allowWorld: {
            type: Boolean,
            default: false,
        },
        characterDefaultInsert: {
            type: String,
            default: 'never',
        },
        worldDefaultInsert: {
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
            insert: this.allowWorld ? this.worldDefaultInsert : this.characterDefaultInsert,
            instructions: '',
            requireActive: true,
            selectedTarget: this.allowWorld ? WORLD_TARGET : '',
        }
    },
    emits: ['create'],
    computed: {
        showTargetSelector() {
            return this.allowWorld || this.characters.length > 0;
        },
        targetItems() {
            let items = this.characters.map(name => ({
                title: name,
                value: name,
                props: { prependIcon: 'mdi-account' },
            }));
            if (this.allowWorld) {
                items.unshift({
                    title: 'World',
                    value: WORLD_TARGET,
                    props: { prependIcon: 'mdi-earth' },
                });
            }
            return items;
        },
        // The world is the target when it is explicitly selected, or when there
        // are no characters to choose from at all.
        isWorldTarget() {
            return this.selectedTarget === WORLD_TARGET || this.characters.length === 0;
        },
        effectiveCharacter() {
            return this.selectedTarget === WORLD_TARGET ? '' : this.selectedTarget;
        },
        hasTargetSelection() {
            if (!this.showTargetSelector) {
                return true;
            }
            return !!this.selectedTarget;
        },
        availableInsertionModes() {
            // conversation-context only makes sense inside a character's own context.
            if (this.isWorldTarget) {
                return this.insertionModes.filter(mode => mode.value !== 'conversation-context');
            }
            return this.insertionModes;
        },
    },
    watch: {
        // Keep the insertion mode aligned with the selected target so switching
        // between World and a character resets to that target's sensible default
        // (and never leaves an invalid mode like conversation-context on world).
        isWorldTarget() {
            this.insert = this.insertDefaultForTarget();
        },
    },
    methods: {
        insertDefaultForTarget() {
            return this.isWorldTarget ? this.worldDefaultInsert : this.characterDefaultInsert;
        },

        open() {
            this.dialog = true;
            this.question = '';
            this.interval = this.defaultInterval;
            this.instructions = '';
            this.requireActive = true;
            this.selectedTarget = this.allowWorld ? WORLD_TARGET : '';
            this.insert = this.insertDefaultForTarget();
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

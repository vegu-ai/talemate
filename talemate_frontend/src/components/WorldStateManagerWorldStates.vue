<template>
    <div v-if="state != null">
        <v-form v-model="formValid" ref="form">
            <v-row>
                <v-col cols="12">
                    <v-text-field 
                        :disabled="!isNewState" 
                        v-model="state.question" 
                        label="Question or State description" 
                        :rules="rules"
                        hint="The ID of the entry. This should be a unique identifier for the entry.">
                    </v-text-field>

                </v-col>
            </v-row>

            <v-row>
                <v-col cols="12">
                    <v-textarea 
                        v-model="state.answer"
                        :label="state.question"
                        :disabled="busy"
                        hint="You can leave this blank as it will be automatically generated. Or you can fill it in to start with a specific answer."
                        :color="dirty ? 'dirty' : ''"
                        @update:model-value="queueSave()"
                        max-rows="15"
                        auto-grow
                        rows="5">
                    </v-textarea>
                </v-col>
            </v-row>

            <v-row>
                <v-col cols="6" xl="3">
                    <v-text-field 
                    v-model="state.interval" 
                    label="Re-inforce / Update detail every N turns" 
                    type="number" 
                    min="1"
                    max="100" 
                    step="1" 
                    class="mb-2" 
                    :disabled="busy"
                    @update:modelValue="queueSave()" 
                    :color="dirty ? 'dirty' : ''">
                    </v-text-field>
                </v-col>
                <v-col cols="6" xl="3">
                    <v-select 
                        v-model="state.insert" :items="insertionModes" 
                        label="Context Attachment Method" 
                        class="mr-1 mb-1" 
                        :disabled="busy"
                        variant="underlined"  
                        density="compact" @update:modelValue="save()" :color="dirty ? 'dirty' : ''">
                    </v-select>
                </v-col>
            </v-row>

            <v-row>
                <v-col cols="12">
                    <v-textarea 
                        v-model="state.instructions"
                        label="Additional instructions to the AI for generating this state."
                        :color="dirty ? 'dirty' : ''"
                        :disabled="busy"
                        @update:model-value="queueSave()"
                        auto-grow
                        max-rows="5"
                        rows="3">
                    </v-textarea>
                </v-col>
            </v-row>

        </v-form>
        <p v-if="busy">
            <v-progress-linear color="primary" height="2" indeterminate></v-progress-linear>
        </p>
        <v-card-actions v-if="isNewState">
            <v-spacer></v-spacer>
            <v-btn @click="save()" color="primary" prepend-icon="mdi-text-box-plus">Create</v-btn>
        </v-card-actions>
        <v-card-actions v-else>
            <ConfirmActionInline @confirm="remove" action-label="Remove State Reinforcement" confirm-label="Confirm removal" />
            <v-spacer></v-spacer>
            <ConfirmActionInline @confirm="runStateReinforcement(true)" action-label="Reset State Reinforcement" confirm-label="Confirm reset" color="warning" icon="mdi-refresh" />
        </v-card-actions>

    </div>


    <div v-else>
        <v-alert color="muted" density="compact" variant="text">
            Set up automatic reinforcement of world information states. This will cause the AI to regularly re-evaluate the state and update the detail accordingly.
            <br><br>
            Add a new state or select an existing one to get started.
            <br><br>
            <v-icon color="orange" class="mr-1">mdi-alert</v-icon> If you want to track states for an acting character, do that through the character manager instead.
        </v-alert>
    </div>

</template>

<script>

import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'WorldStateManagerWorldEntries',
    components: {
        ConfirmActionInline,
    },
    props: {
        templates: Object,
        generationOptions: Object,
        immutableStates: Object,
    },
    computed: {
        isNewState() {
            return this.state && this.state.isNew;
        },
    },
    data() {
        return {
            states: {},
            selected: null,
            timeout: null,
            state: null,
            busy: false,
            dirty: false,
            formValid: false,
            rules: [
                v => !!v || 'Question is required',
                // make sure id doesn't already exist
                v => {
                    if(this.states[v] && this.isNewState) {
                        return 'Question already exists';
                    }
                    return true;
                }
            ]
        }
    },
    emits:[
        'require-scene-save',
        'load-pin',
        'add-pin',
        'request-sync',
    ],
    inject: [
        'insertionModes',
        'getWebsocket',
        'loadContextDBEntry',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'requestWorld',
    ],
    watch: {
        immutableStates: {
            immediate: true,
            handler(states) {
                this.states = {...states}
            }
        },
    },
    methods: {
        queueSave(delay = 1500) {
            if(this.isNewState) {
                return;
            }

            if (this.timeout !== null) {
                clearTimeout(this.timeout);
            }

            this.dirty = true;

            this.timeout = setTimeout(() => {
                this.save();
            }, delay);
        },

        save(updateState) {
            this.busy = true;
            this.$refs.form.validate();
            if(!this.formValid) {
                return;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_world_state_reinforcement',
                question: this.state.question,
                answer: this.state.answer,
                instructions: this.state.instructions,
                interval: this.state.interval,
                insert: this.state.insert,
                update_state: updateState || this.state.isNew,
            }));
            if(this.state.isNew) {
                this.state.isNew = false;
            }
        },

        create() {
            this.state = {
                question: '',
                answer: '',
                instructions: '',
                interval: 10,
                insert: 'never',
                isNew: true,
            };
        },

        select(id) {
            console.log({id, states: this.states})
            this.state = this.states[id];
            this.$nextTick(() => {
                this.dirty = false;
                this.$refs.form.validate();
            });
        },

        remove() {
            if(this.state == null || this.state.isNew) {
                this.state = null;
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_world_state_reinforcement',
                question: this.state.question,
            }));

            this.state = null;
        },

        runStateReinforcement(reset) {
            this.busy=true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'run_world_state_reinforcement',
                question: this.state.question,
                reset: reset || false,
            }));

            this.resetStateReinforcerConfirm = false;
        },

        // responses
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
            if (message.action == 'world_state_reinforcement_set') {
                this.dirty = false;
                if(message.data.question === this.state.question) {
                    this.state.answer = message.data.answer;
                }
            } else if (message.action == 'world_state_reinforcement_deleted') {
                this.selected = null;
            } else if (message.action == 'world_state_reinforcement_ran') {
                this.busy = false;
                if(message.data.question === this.state.question) {
                    this.state.answer = message.data.answer;
                }
            } else if(message.action === 'operation_done') {
                this.busy = false;
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>
<template>
    <v-card flat>
        <v-card-text>
            <v-row>
                <v-col cols="3">
                    <v-list dense v-if="pinsExist">
                        <v-list-item prepend-icon="mdi-help" @click.stop="selected = null">
                            <v-list-item-title>Information</v-list-item-title>
                        </v-list-item>
                        <v-list-item v-for="pin in pins" :key="pin.pin.entry_id"
                            @click.stop="selectPin(pin.pin.entry_id)"
                            :prepend-icon="pin.pin.active ? 'mdi-pin' : 'mdi-pin-off'"
                            :class="pin.pin.active ? '' : 'inactive'">
                            <v-list-item-title>{{ pin.text }}</v-list-item-title>
                            <v-list-item-subtitle>

                            </v-list-item-subtitle>
                        </v-list-item>
                    </v-list>
                    <v-card v-else>
                        <v-card-text>
                            No pins defined.
                        </v-card-text>
                    </v-card>
                </v-col>
                <v-col cols="9">
                    <v-row v-if="selected != null && selectedPin != null">
                        <v-col cols="7">
                            <v-card>
                                <v-checkbox hide-details dense v-model="pins[selected].pin.active"
                                    label="Pin active" @change="update(selected)"></v-checkbox>
                                <v-alert class="mb-2 pre-wrap" variant="text" color="grey"
                                    icon="mdi-book-open-page-variant">
                                    <div class="formatted-text">
                                        {{ selectedPin.text }}
                                    </div>
                                </v-alert>
                                <v-card-actions>
                                    <ConfirmActionInline action-label="Remove pin" confirm-label="Confirm removal"
                                        @confirm="remove(selected)" />
                                    <v-spacer></v-spacer>
                                    <v-btn variant="text" color="primary"
                                        @click.stop="loadContextDBEntry(selected)"
                                        prepend-icon="mdi-book-open-page-variant">View in context DB</v-btn>
                                </v-card-actions>
                            </v-card>
                        </v-col>
                        <v-col cols="5">
                            <v-card>
                                <v-card-title><v-icon size="small">mdi-robot</v-icon> Conditional auto
                                    pinning</v-card-title>
                                <v-card-text>
                                    <v-textarea rows="1" auto-grow v-model="pins[selected].pin.condition"
                                        label="Condition question prompt for auto pinning"
                                        hint="The condition that must be met for the pin to be active. Prompt will be evaluated by the AI (World State agent) regularly. This should be a question that the AI can answer with a yes or no."
                                        @update:model-value="queueUpdate(selected)">
                                    </v-textarea>
                                    <v-slider
                                        min="0"
                                        max="100"
                                        step="1"
                                        v-model="pins[selected].pin.decay"
                                        label="Decay"
                                        thumb-label="always"
                                        hint="Number of rounds this pin stays active once activated. 0 means no decay. You do NOT need to set a condition for this to work."
                                        @change="update(selected)"
                                    />
                                    <v-slider v-if="pins[selected].pin.decay_due > 0"
                                        min="0"
                                        :max="pins[selected].pin.decay"
                                        step="1"
                                        color="brown-darken-2"
                                        v-model="pins[selected].pin.decay_due"
                                        label="Active decay counter"
                                        thumb-label="always"
                                        hint="Active decay counter for this pin."
                                        @change="update(selected)"
                                    />
                                    <v-checkbox hide-details dense v-model="pins[selected].pin.condition_state"
                                        label="Current condition evaluation"
                                        @change="update(selected)"></v-checkbox>
                                </v-card-text>
                            </v-card>
                        </v-col>


                    </v-row>
                    <v-alert v-else type="info" color="grey" variant="text" icon="mdi-pin">
                        Pins allow you to permanently pin a context entry to the AI context. While a pin is
                        active, the AI will always consider the pinned entry when generating text. <v-icon
                            color="warning">mdi-alert</v-icon> Pinning too many entries may use up your
                        available context size, so use them wisely.

                        <br><br>
                        Additionally you may also define auto pin conditions that the World State agent will
                        check every turn. If the condition is met, the entry will be pinned. If the
                        condition
                        is no longer met, the entry will be unpinned.

                        <br><br>
                        Finally, remember there is also automatic insertion of context based on relevance to
                        the current scene progress, which happens regardless of pins. Pins are just a way to
                        ensure that a specific entry is always considered relevant.

                        <br><br>
                        <v-btn color="primary" variant="text" prepend-icon="mdi-plus"
                            @click.stop="loadContextDBEntry()">Add new pins through the context
                            manager.</v-btn>

                    </v-alert>

                </v-col>
            </v-row>
        </v-card-text>
    </v-card>
</template>

<script>

import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'WorldStateManagerPins',
    components: {
        ConfirmActionInline,
    },
    data() {
        return {
            pins: {},
            selected: null,
            updateTimeout: null,
        }
    },
    emits:[
        'require-scene-save',
    ],
    props: {
        immutablePins: Object,
    },
    watch: {
        immutablePins: {
            immediate: true,
            handler(value) {
                if (!value) {
                    this.pins = null;
                } else {
                    this.pins = { ...value };
                }
            }
        }
    },
    computed: {
        selectedPin() {

            if (this.selected === null) {
                return null;
            }

            return this.pins[this.selected];
        },
        pinsExist() {
            return Object.keys(this.pins).length > 0;
        },
    },
    inject: [
        'getWebsocket',
        'registerMessageHandler',
        'loadContextDBEntry',
    ],
    methods: {

        reset() {
            this.selected = null;
            this.pins = {};
        },

        entryHasPin(entryId) {
            return this.pins[entryId] !== undefined;
        },

        entryIsPinned(entryId) {
            return this.entryHasPin(entryId) && this.pins[entryId].pin.active;
        },

        selectPin(entryId) {
            this.selected = entryId
        },

        add(entryId) {

            this.pins[entryId] = {
                text: "",
                pin: {
                    entry_id: entryId,
                    active: false,
                    condition: "",
                    condition_state: false,
                }
            };
            this.selectPin(entryId);

            this.update(entryId);
        },

        remove(entryId) {
            delete this.pins[entryId];
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'remove_pin',
                entry_id: entryId,
            }));
            this.selected = null;
            this.removeConfirm = false;
        },

        update(entryId) {

            let pin = this.pins[entryId];

            if(pin === undefined) {
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_pin',
                entry_id: pin.pin.entry_id,
                active: pin.pin.active,
                condition: pin.pin.condition,
                condition_state: pin.pin.condition_state,
                decay: (pin.pin.decay && pin.pin.decay > 0) ? pin.pin.decay : null,
            }));
        },

        queueUpdate(pin) {
            if (this.updateTimeout !== null) {
                clearTimeout(this.updateTimeout);
            }

            this.updateTimeout = setTimeout(() => {
                this.update(pin);
            }, 500);
        },
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
        },
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>

<style scoped>
.formatted-text {
    white-space: pre-wrap;
}
</style>
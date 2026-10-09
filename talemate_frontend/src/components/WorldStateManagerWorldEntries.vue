<template>
    <v-row>
        <v-col cols="12">
            <v-card v-if="entry != null">
                <v-form v-model="formValid" ref="form" @submit.prevent>
                    <v-text-field 
                        :disabled="!isNewEntry || creating" 
                        v-model="entry.id" label="Entry ID" 
                        :rules="rules"
                        hint="The ID of the entry. This should be a unique identifier for the entry."
                        @keyup.enter.prevent="focusText"
                    >
                    </v-text-field>
                    <ContextualGenerate 
                        :context="'world context:'+entry.id" 
                        :original="entry.text"
                        :requires-instructions="true"
                        :generation-options="generationOptions"
                        :specify-length="true"
                        :length="512"
                        :disabled="creating"
                        @generate="content => { entry.text=content; queueSave(500); dirty = true; }"
                    />
                    <div class="position-relative">
                        <v-textarea
                            ref="textInput"
                            v-model="entry.text"
                            label="World information"
                            :hint="'Describe the world information here. This could be a description of a location, a historical event, or anything else that is relevant to the world. '+autocompleteInfoMessage(worldInfoBusy)"
                            :color="dirty ? 'dirty' : ''"
                            :disabled="worldInfoBusy || creating"
                            :loading="worldInfoBusy"
                            @update:model-value="dirty = true"
                            @keyup.ctrl.enter.stop="sendWorldInfoAutocomplete"
                            @blur="handleBlur"
                            auto-grow
                            rows="5">
                        </v-textarea>
                        <AutocompleteRedoChip
                            :applied="worldInfoAutocompleteField?.state.applied || false"
                            :disabled="worldInfoBusy"
                            @redo="worldInfoAutocompleteField.redo()"
                            @undo="worldInfoAutocompleteField.undo()" />
                    </div>

                    <v-row>
                        <v-col cols="12" md="6">
                            <v-checkbox v-model="entry.meta['pin_only']" 
                            label="Include only when pinned" 
                            :disabled="creating"
                            :hint="(
                                entry.meta['pin_only'] ? 
                                'This entry will only be included when pinned and never be included via automatic relevancy matching.' :
                                'This entry may be included via automatic relevancy matching.'
                            )"
                            @change="save()"></v-checkbox>
                        </v-col>
                        <v-col cols="12" md="6" v-if="!isNewEntry">
                            <v-card class="mt-2" elevation="2" :color="entry.shared ? 'highlight6' : 'muted'" variant="tonal">
                                <v-card-text>
                                    <v-checkbox v-model="entry.shared" label="Shared to World Context" @change="save()"  messages="Share this entry with other scenes linked to the same shared context."></v-checkbox>
                                </v-card-text>
                            </v-card>
                        </v-col>
                        <v-col cols="12" v-if="!isNewEntry">
                            <EntryVisibilitySelect
                                :model-value="entry.visibility"
                                owner-label="nobody"
                                @update:model-value="setVisibility" />
                        </v-col>
                    </v-row>

                </v-form>

                <v-alert v-if="error" type="error" variant="tonal" density="compact" closable class="mx-4 mb-2" @click:close="error = null">{{ error }}</v-alert>
                <v-card-actions v-if="isNewEntry">
                    <v-spacer></v-spacer>
                    <v-btn @click="createEntry" color="primary" prepend-icon="mdi-text-box-plus" :loading="creating" :disabled="creating">Create</v-btn>
                </v-card-actions>
                <v-card-actions v-else>
                    <ConfirmActionInline @confirm="remove" action-label="Remove Entry" confirm-label="Confirm removal" />
                    <v-spacer></v-spacer>
                    <v-btn v-if="entryHasPin" @click="$emit('load-pin', entry.id)" color="primary" prepend-icon="mdi-pin">View pin</v-btn>
                    <v-btn v-else @click="addPin" color="primary" prepend-icon="mdi-pin" :loading="pinPending" :disabled="pinPending">Add pin</v-btn>
                </v-card-actions>
            </v-card>
            <v-card v-else>
                <v-alert color="muted" density="compact" variant="text">
                    Add world information / lore and add extra details.
                    <br><br>
                    Add a new entry or select an existing one to get started.
                    <br><br>
                    <v-icon color="warning" class="mr-1">mdi-alert</v-icon> If you want to add details to an acting character do that through the character manager instead.
                </v-alert>
            </v-card>

        </v-col>
        <v-col cols="12"></v-col>
    </v-row>

</template>

<script>

import ContextualGenerate from './ContextualGenerate.vue';
import ConfirmActionInline from './ConfirmActionInline.vue';
import EntryVisibilitySelect from './EntryVisibilitySelect.vue';
import AutocompleteRedoChip from './AutocompleteRedoChip.vue';
import { createAutocompleteField } from '@/utils/autocompleteField';

export default {
    name: 'WorldStateManagerWorldEntries',
    components: {
        EntryVisibilitySelect,
        ContextualGenerate,
        ConfirmActionInline,
        AutocompleteRedoChip,
    },
    props: {
        pins: Object,
        templates: Object,
        generationOptions: Object,
        immutableEntries: Object,
    },
    computed: {
        isNewEntry() {
            return this.entry && this.entry.isNew;
        },
        entryHasPin() {
            return this.entry && this.pins[this.entry.id];
        },
        creating() {
            return this.creatingId !== null;
        },
        pinPending() {
            return !!this.entry && this.pinRequestedFor === this.entry.id;
        },
    },
    data() {
        return {
            entries: {},
            selected: null,
            timeout: null,
            entry: null,
            dirty: false,
            worldInfoBusy: false,
            worldInfoAutocompleteField: null,
            formValid: false,
            // the id a running Create saved; the card binds to that entry once it arrives
            creatingId: null,
            pinRequestedFor: null,
            error: null,
            rules: [
                v => !!v || 'Entry ID is required',
                // make sure id doesn't already exist
                v => {
                    if(this.entries[v] && this.isNewEntry) {
                        return 'Entry ID already exists';
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
        'autocompleteInfoMessage',
        'autocompleteRequest',
    ],
    watch: {
        immutableEntries: {
            immediate: true,
            handler(entries) {
                this.entries = {...entries}
                this.$nextTick(() => {
                    if (this.creating && this.entries[this.creatingId]) {
                        this.select(this.creatingId);
                        return;
                    }
                    // a draft keeps its own fields even when its id matches a saved entry
                    if (this.isNewEntry) {
                        return;
                    }
                    const currentId = (this.entry && this.entry.id) || this.selected;
                    if (currentId && this.entries[currentId]) {
                        this.entry = this.entries[currentId];
                    }
                });
            }
        },
        pins() {
            if (this.pinRequestedFor && this.pins[this.pinRequestedFor]) {
                this.pinRequestedFor = null;
            }
        },
        'entry.text'() {
            this.worldInfoAutocompleteField?.onValueChange();
        },
    },
    created() {
        this.worldInfoAutocompleteField = createAutocompleteField({
            autocompleteRequest: this.autocompleteRequest,
            getValue: () => this.entry?.text || '',
            setValue: (v) => {
                if (!this.entry) return;
                this.entry.text = v;
                // Programmatic writes bypass @update:model-value; flag dirty so the completion persists.
                this.dirty = true;
            },
            buildParams: () => ({
                partial: this.entry.text,
                context: `world context:${this.entry.id}`,
            }),
            onStart: () => { this.worldInfoBusy = true; },
            onEnd: () => { this.worldInfoBusy = false; },
        });
    },
    methods: {
        setVisibility(visibility) {
            this.entry.visibility = visibility;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_world_entry_visibility',
                entry_id: this.entry.id,
                visibility: visibility,
            }));
        },
        queueSave(delay = 1500) {

            if(this.isNewEntry) {
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

        // autosave of an existing entry; a draft is only saved by createEntry
        save(only_if_dirty = false) {

            if(this.isNewEntry) {
                return;
            }

            if(only_if_dirty && !this.dirty) {
                return;
            }

            this.$refs.form.validate();
            if(!this.formValid) {
                return;
            }
            this.sendSave();
        },

        async createEntry() {
            if(!this.isNewEntry || this.creating) {
                return;
            }
            const { valid } = await this.$refs.form.validate();
            if(!valid) {
                return;
            }
            this.error = null;
            this.creatingId = this.entry.id;
            this.sendSave();
        },

        sendSave() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_world_entry',
                id: this.entry.id,
                text: this.entry.text,
                meta: this.entry.meta,
                shared: this.entry.shared,
            }));
        },

        addPin() {
            this.error = null;
            this.pinRequestedFor = this.entry.id;
            this.$emit('add-pin', this.entry.id);
        },

        create() {
            this.creatingId = null;
            this.error = null;
            this.selected = null;
            this.entry = {
                id: '',
                text: '',
                meta: {},
                isNew: true,
                shared: false,
            };
        },

        select(id) {
            if (!this.entries[id]) {
                console.warn(`Entry "${id}" not found`);
                return;
            }
            this.entry = this.entries[id];
            this.selected = id;
            this.creatingId = null;
            this.error = null;
            this.$nextTick(() => {
                this.dirty = false;
                this.$refs.form.validate();
            });
        },

        remove() {
            if(this.entry == null || this.entry.isNew) {
                this.entry = null;
                return;
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_world_entry',
                id: this.entry.id
            }));

            this.entry = null;
        },

        // responses
        focusText() {
            // Move focus to the world information textarea when Enter is pressed in Entry ID field
            this.$nextTick(() => {
                if (this.$refs.textInput && this.$refs.textInput.focus) {
                    this.$refs.textInput.focus();
                }
            });
        },
        handleBlur() {
            // Guard: blur during autocomplete would save the un-stripped {hint}.
            if (this.worldInfoBusy) {
                return;
            }
            // Only auto-save on blur for existing entries, not new ones
            if (!this.isNewEntry) {
                this.save(true);
            }
        },

        handleFailure(message) {
            if (message.failed_action === 'save_world_entry' && this.creating) {
                this.creatingId = null;
                this.error = `The entry was not created: ${message.error.message}`;
            } else if (message.failed_action === 'set_pin' && this.pinRequestedFor) {
                this.pinRequestedFor = null;
                this.error = `The pin was not added: ${message.error.message}`;
            }
        },

        sendWorldInfoAutocomplete() {
            this.worldInfoAutocompleteField.request(this.$refs.textInput);
        },

        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
            
            if (message.action == 'world_entry_saved') {
                this.dirty = false;
            } else if (message.action == 'world_entry_deleted') {
                this.selected = null;
                this.busy = false;
            } else if(message.action === 'operation_done') {
                this.busy = false;
                if (message.error) {
                    this.handleFailure(message);
                }
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>
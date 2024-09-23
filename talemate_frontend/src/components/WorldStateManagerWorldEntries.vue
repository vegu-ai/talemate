<template>
    <div  v-if="entry != null">
        <v-form v-model="formValid" ref="form">
            <v-text-field 
                :disabled="!isNewEntry" 
                v-model="entry.id" label="Entry ID" 
                :rules="rules"
                hint="The ID of the entry. This should be a unique identifier for the entry.">
            </v-text-field>
            <ContextualGenerate 
                :context="'world context:'+entry.id" 
                :original="entry.text"
                :requires-instructions="true"
                :generation-options="generationOptions"
                @generate="content => { entry.text=content; queueSave(500); }"
            />
            <v-textarea 
                v-model="entry.text"
                label="World information"
                hint="Describe the world information here. This could be a description of a location, a historical event, or anything else that is relevant to the world." 
                :color="dirty ? 'dirty' : ''"
                @update:model-value="queueSave()"
                auto-grow
                max-rows="24"
                rows="5">
            </v-textarea>
            <v-checkbox v-model="entry.meta['pin_only']" 
            label="Include only when pinned" 
            :hint="(
                entry.meta['pin_only'] ? 
                'This entry will only be included when pinned and never be included via automatic relevancy matching.' :
                'This entry may be included via automatic relevancy matching.'
            )"
            @change="queueSave(500)"></v-checkbox>
        </v-form>

        <v-card-actions v-if="isNewEntry">
            <v-spacer></v-spacer>
            <v-btn @click="save" color="primary" prepend-icon="mdi-text-box-plus">Create</v-btn>
        </v-card-actions>
        <v-card-actions v-else>
            <ConfirmActionInline @confirm="remove" action-label="Remove Entry" confirm-label="Confirm removal" />
            <v-spacer></v-spacer>
            <v-btn v-if="entryHasPin" @click="$emit('load-pin', entry.id)" color="primary" prepend-icon="mdi-pin">View pin</v-btn>
            <v-btn v-else @click="$emit('add-pin', entry.id)" color="primary" prepend-icon="mdi-pin">Add pin</v-btn>
        </v-card-actions>
    </div>


    <div v-else>
        <v-alert color="muted" density="compact" variant="text">
            Add world information / lore and add extra details.
            <br><br>
            Add a new entry or select an existing one to get started.
            <br><br>
            <v-icon color="orange" class="mr-1">mdi-alert</v-icon> If you want to add details to an acting character do that through the character manager instead.
        </v-alert>
    </div>

</template>

<script>

import ContextualGenerate from './ContextualGenerate.vue';
import ConfirmActionInline from './ConfirmActionInline.vue';

export default {
    name: 'WorldStateManagerWorldEntries',
    components: {
        ContextualGenerate,
        ConfirmActionInline,
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
    },
    data() {
        return {
            entries: {},
            selected: null,
            timeout: null,
            entry: null,
            dirty: false,
            formValid: false,
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
    ],
    watch: {
        immutableEntries: {
            immediate: true,
            handler(entries) {
                this.entries = {...entries}
            }
        },
    },
    methods: {
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

        save() {
            this.$refs.form.validate();
            if(!this.formValid) {
                return;
            }
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'save_world_entry',
                id: this.entry.id,
                text: this.entry.text,
                meta: this.entry.meta,
            }));
            if(this.entry.isNew) {
                this.entry.isNew = false;
            }
        },

        create() {
            this.entry = {
                id: '',
                text: '',
                meta: {},
                isNew: true,
            };
        },

        select(id) {
            console.log({id, entries: this.entries})
            this.entry = this.entries[id];
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
            }
        },
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
}

</script>
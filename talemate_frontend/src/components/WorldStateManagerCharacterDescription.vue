<template>

    <ContextualGenerate 
        ref="contextualGenerate"
        uid="wsm.character_description"
        :context="'character detail:description'" 
        :original="character.description"
        :character="character.name"
        :generationOptions="generationOptions"
        :templates="templates"
        @generate="content => setAndUpdate(content)"
    />

    <v-textarea ref="description" rows="5" auto-grow v-model="character.description"
        :color="dirty ? 'dirty' : ''"

        :disabled="busy"
        :loading="busy"
        @keyup.ctrl.enter.stop="sendAutocompleteRequest"

        @update:model-value="queueUpdate()"
        label="Description"
        :hint="'A short description of the character. '+autocompleteInfoMessage(busy)">
    </v-textarea>

    <SpiceAppliedNotification :uids="['wsm.character_description']"></SpiceAppliedNotification>

</template>
<script>

import ContextualGenerate from './ContextualGenerate.vue';
import SpiceAppliedNotification from './SpiceAppliedNotification.vue';

export default {
    name: 'WorldStateManagerCharacterDescription',
    components: {
        ContextualGenerate,
        SpiceAppliedNotification,
    },
    props: {
        immutableCharacter: Object,
        templates: Object,
        generationOptions: Object,
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
        'unregisterMessageHandler',
    ],
    emits:[
        'require-scene-save'
    ],
    data() {
        return {
            character: {},
            dirty: false,
            busy: false,
            updateTimeout: null,
            spiceApplied: false,
            spiceAppliedDetail: null, 
        }
    },
    watch: {
        immutableCharacter: {
            immediate: true,
            handler(value) {
                if (!value) {
                    this.character = null;
                } else {
                    this.character = { ...value };
                }
            }
        }
    },
    methods: {
        queueUpdate(delay = 1500) {
            if (this.updateTimeout !== null) {
                clearTimeout(this.updateTimeout);
            }

            this.dirty = true;

            this.updateTimeout = setTimeout(() => {
                this.update();
            }, delay);
        },
        update() {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_description',
                name: this.character.name,
                attribute: 'description',
                value: this.character.description,
            }));
        },

        setAndUpdate(value) {
            this.character.description = value;
            this.update();
        },

        sendAutocompleteRequest() {
            this.busy = true;
            this.autocompleteRequest({
                partial: this.character.description,
                context: `character detail:description`,
                character: this.character.name
            }, (completion) => {
                this.character.description += completion;
                this.busy = false;
            }, this.$refs.description);
        },

        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
            else if (message.action === 'character_description_updated') {
                this.dirty = false;
                this.$emit('require-scene-save');
            }
        }
    },
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}

</script>
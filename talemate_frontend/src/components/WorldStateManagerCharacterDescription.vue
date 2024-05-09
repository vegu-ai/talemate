<template>
    <ContextualGenerate 
        :context="'character detail:description'" 
        :original="character.description"
        :character="character.name"
        @generate="content => setAndUpdate(content)"
    />

    <v-textarea ref="description" rows="5" auto-grow v-model="character.description"
        :color="dirty ? 'info' : ''"

        :disabled="busy"
        :loading="busy"
        @keyup.ctrl.enter.stop="sendAutocompleteRequest"

        @update:model-value="queueUpdate"
        label="Description"
        :hint="'A short description of the character. '+autocompleteInfoMessage(busy)"></v-textarea>
</template>
<script>

import ContextualGenerate from './ContextualGenerate.vue';

export default {
    name: 'WorldStateManagerCharacterDescription',
    components: {
        ContextualGenerate,
    },
    props: {
        immutableCharacter: Object
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
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
        queueUpdate() {
            if (this.updateTimeout !== null) {
                clearTimeout(this.updateTimeout);
            }

            this.dirty = true;

            this.updateTimeout = setTimeout(() => {
                this.update();
            }, 500);
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
            console.log("Setting and updating DESCRIPTION?!?!?!?!", value)
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
            if (message.action === 'character_description_updated') {
                this.dirty = false;
                this.$emit('require-scene-save');
            }
        }
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}

</script>
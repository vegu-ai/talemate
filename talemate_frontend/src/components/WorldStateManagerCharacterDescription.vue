<template>

    <v-row>
        <v-col cols="12" md="10" lg="8">
            <GenerationOptions :templates="templates" ref="generationOptions" @change="(opt) => { generationOptions = opt }" />
        </v-col>
        <v-col cols="12" md="2" lg="4">
            <ContextualGenerate 
                :context="'character detail:description'" 
                :original="character.description"
                :character="character.name"
                :generationOptions="generationOptions"
                @generate="content => setAndUpdate(content)"
            />
        </v-col>
    </v-row>



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
import GenerationOptions from './GenerationOptions.vue';

export default {
    name: 'WorldStateManagerCharacterDescription',
    components: {
        ContextualGenerate,
        GenerationOptions,
    },
    props: {
        immutableCharacter: Object,
        templates: Object,
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
            generationOptions: {},
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
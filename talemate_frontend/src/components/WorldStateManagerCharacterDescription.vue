<template>

    <v-row>
        <v-col cols="12" md="10" lg="8">
            <GenerationOptions :templates="templates" ref="generationOptions" @change="(opt) => { generationOptions = opt }" />
        </v-col>
        <v-col cols="12" md="2" lg="4">
            <ContextualGenerate 
                ref="contextualGenerate"
                :context="'character detail:description'" 
                :original="character.description"
                :character="character.name"
                :generationOptions="generationOptions"
                :templates="templates"
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
        :hint="'A short description of the character. '+autocompleteInfoMessage(busy)">
    </v-textarea>

    <v-snackbar color="grey-darken-4" location="top" v-model="spiceApplied" :timeout="5000" max-width="400" multi-line>
        <div class="text-caption text-highlight4">
            <v-icon color="highlight4">mdi-chili-mild</v-icon>
            Spice applied!
        </div>
        {{ spiceAppliedDetail }}
    </v-snackbar>

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
            generationOptions: {},
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
            if (message.type === 'spice_applied' && message.data.uid === this.$refs.contextualGenerate.uid) {
                this.spiceAppliedDetail = `${message.data.context[1]}: ${message.data.spice}`;
                this.spiceApplied = true;
            } else if (message.type !== 'world_state_manager') {
                return;
            }

            if (message.action === 'character_description_updated') {
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
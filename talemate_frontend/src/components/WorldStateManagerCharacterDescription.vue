<template>

    <ContextualGenerate 
        ref="contextualGenerate"
        uid="wsm.character_description"
        :context="'character detail:description'" 
        :original="character.description"
        :character="character.name"
        :generationOptions="generationOptions"
        :templates="templates"
        :specifyLength="true"
        @generate="content => setAndUpdate(content)"
    />

    <div class="position-relative">
        <v-textarea ref="description" rows="5" auto-grow v-model="character.description"
            :color="dirty ? 'dirty' : ''"

            :disabled="busy"
            :loading="busy"
            @keyup.ctrl.enter.stop="sendAutocompleteRequest"

            @update:model-value="dirty = true"
            @blur="onBlurSave"
            label="Description"
            :hint="'A short description of the character. '+autocompleteInfoMessage(busy)">
        </v-textarea>
        <AutocompleteRedoChip
            :applied="descriptionAutocompleteField?.state.applied || false"
            :disabled="busy"
            @redo="descriptionAutocompleteField.redo()"
            @undo="descriptionAutocompleteField.undo()" />
    </div>

    <SpiceAppliedNotification :uids="['wsm.character_description']"></SpiceAppliedNotification>

</template>
<script>

import ContextualGenerate from './ContextualGenerate.vue';
import SpiceAppliedNotification from './SpiceAppliedNotification.vue';
import AutocompleteRedoChip from './AutocompleteRedoChip.vue';
import { createAutocompleteField } from '@/utils/autocompleteField';

export default {
    name: 'WorldStateManagerCharacterDescription',
    components: {
        ContextualGenerate,
        SpiceAppliedNotification,
        AutocompleteRedoChip,
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
            descriptionAutocompleteField: null,
        }
    },
    created() {
        this.descriptionAutocompleteField = createAutocompleteField({
            autocompleteRequest: this.autocompleteRequest,
            getValue: () => this.character?.description || '',
            setValue: (v) => { if (this.character) this.character.description = v; },
            buildParams: () => ({
                partial: this.character.description,
                context: `character detail:description`,
                character: this.character.name,
            }),
            onStart: () => { this.busy = true; },
            onEnd: () => { this.busy = false; },
        });
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
        },
        'character.description'() {
            this.descriptionAutocompleteField?.onValueChange();
        },
    },
    methods: {
        update(only_if_dirty = false) {

            if(only_if_dirty && !this.dirty) {
                return;
            }

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

        onBlurSave() {
            // Guard: blur during autocomplete would save the un-stripped {hint}.
            if (this.busy) return;
            this.update(true);
        },

        sendAutocompleteRequest() {
            this.descriptionAutocompleteField.request(this.$refs.description);
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
<template>
    <v-row floating color="grey-darken-5">
        <v-col cols="3">
            <v-text-field v-model="search"
                label="Filter details" append-inner-icon="mdi-magnify"
                clearable density="compact" variant="underlined"
                class="ml-1 mb-1 mt-1"
                @update:model-value="autoSelect"></v-text-field>
        </v-col>
        <v-col cols="3"></v-col>
        <v-col cols="2"></v-col>
        <v-col cols="4">
            <v-text-field v-model="newName"
                label="New detail" append-inner-icon="mdi-plus"
                class="mr-1 mb-1 mt-1" variant="underlined" density="compact"
                @keyup.enter="handleNew"
                hint="Descriptive name or question."></v-text-field>
        </v-col>
    </v-row>
    <v-divider></v-divider>
    <v-row>
        <v-col cols="4">
            <v-tabs direction="vertical" density="compact" v-model="selected" color="indigo-lighten-3">
                <v-tab v-for="(value, detail) in filteredList"
                    :key="detail"
                    class="text-caption"
                    :value="detail">
                    <v-list-item-title class="text-caption">{{ detail }}</v-list-item-title>
                </v-tab>
            </v-tabs>
        </v-col>
        <v-col cols="8">
            <div v-if="selected && character.details[selected] !== undefined">

                <ContextualGenerate 
                    :context="'character detail:'+selected" 

                    :original="character.details[selected]"

                    :character="character.name"

                    @generate="content => setAndUpdate(selected, content)"
                />


                <v-textarea rows="5" max-rows="10" auto-grow
                    ref="detail"
                    :color="dirty ? 'info' : ''"

                    :disabled="busy"
                    :loading="busy"
                    :hint="autocompleteInfoMessage(busy)"

                    @keyup.ctrl.enter.stop="sendAutocompleteRequest"

                    @update:modelValue="queueUpdate(selected)"
                    :label="selected"
                    v-model="character.details[selected]">
                </v-textarea>


            </div>

            <v-row v-if="selected && character.details[selected] !== undefined">
                <v-col cols="6">
                    <v-btn v-if="removeConfirm === false"
                        rounded="sm" prepend-icon="mdi-close-box-outline" color="error"
                        variant="text"
                        @click.stop="removeConfirm = true">
                        Remove detail
                    </v-btn>
                    <div v-else>
                        <v-btn rounded="sm" prepend-icon="mdi-close-box-outline"
                            @click.stop="remove(selected)"
                            color="error" variant="text">
                            Confirm removal
                        </v-btn>
                        <v-btn class="ml-1" rounded="sm"
                            prepend-icon="mdi-cancel"
                            @click.stop="removeConfirm = false"
                            color="info" variant="text">
                            Cancel
                        </v-btn>
                    </div>

                </v-col>
                <v-col cols="6" class="text-right">
                    <div
                        v-if="character.reinforcements[selected]">
                        <v-btn rounded="sm"
                            prepend-icon="mdi-image-auto-adjust"
                            @click.stop="viewCharacterStateReinforcer(selected)"
                            color="primary" variant="text">
                            Manage auto state
                        </v-btn>
                    </div>
                    <div v-else>
                        <v-btn rounded="sm"
                            prepend-icon="mdi-image-auto-adjust"
                            @click.stop="viewCharacterStateReinforcer(selected)"
                            color="primary" variant="text">
                            Setup auto state
                        </v-btn>
                    </div>
                </v-col>
            </v-row>

        </v-col>
    </v-row>
</template>

<script>
import ContextualGenerate from './ContextualGenerate.vue';

export default {
    name: 'WorldStateManagerCharacterDetails',
    components: {
        ContextualGenerate,
    },
    props: {
        immutableCharacter: Object
    },
    data() {
        return {
            selected: null,
            newName: null,
            newValue: null,
            removeConfirm: false,
            search: null,
            dirty: false,
            busy: false,
            updateTimeout: null,
            character: null,
        }
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
    ],
    emits:[
        'require-scene-save',
        'load-character-state-reinforcement'
    ],
    watch: {
        immutableCharacter: {
            immediate: true,
            handler(value) {
                if(value && this.character && value.name !== this.character.name) {
                    this.character = null;
                    this.selected = null;
                    this.newName = null;
                }
                if (!value) {
                    this.character = null;
                } else {
                    this.character = { ...value };
                }
            }
        }
    },
    computed: {
        filteredList() {
            if(!this.character) {
                return {};
            }

            if (!this.search) {
                return this.character.details;
            }

            let result = {};
            for (let detail in this.character.details) {
                if (detail.toLowerCase().includes(this.search.toLowerCase()) || detail === this.selected) {
                    result[detail] = this.character.details[detail];
                }
            }
            return result;
        },
    },
    methods: {

        autoSelect() {
            this.selected = null;
            // if there is only one detail in the filtered list, select it
            if (Object.keys(this.filteredList).length > 0) {
                this.selected = Object.keys(this.filteredList)[0];
            }
        },

        queueUpdate(name) {
            if (this.updateTimeout !== null) {
                clearTimeout(this.updateTimeout);
            }

            this.dirty = true;

            this.updateTimeout = setTimeout(() => {
                this.update(name);
            }, 500);
        },

        update(name) {
            return this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_detail',
                name: this.character.name,
                detail: name,
                value: this.character.details[name],
            }));
        },

        setAndUpdate(name, value) {
            this.character.details[name] = value;
            this.update(name);
        },

        handleNew() {
            this.character.details[this.newName] = "";
            this.selected = this.newName;
            this.newName = null;
            // set focus to the new detail
            this.$nextTick(() => {
                this.$refs.detail.focus();
            });
        },

        remove(name) {
            // set value to blank
            this.character.details[name] = "";
            this.removeConfirm = false;
            // send update
            this.update(name);
            // remove detail from list
            delete this.character.details[name];
            this.selected = null;
        },

        sendAutocompleteRequest() {
            this.busy = true;
            this.autocompleteRequest({
                partial: this.character.details[this.selected],
                context: `character detail:${this.selected}`,
                character: this.character.name
            }, (completion) => {
                this.character.details[this.selected] += completion;
                this.busy = false;
            }, this.$refs.detail);

        },
        
        viewCharacterStateReinforcer(name) {
            this.$emit('load-character-state-reinforcement', name)
        },

        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }
            if (message.action === 'character_detail_updated') {
                this.dirty = false;
                this.$emit('require-scene-save');
            }
        }
    },
    mounted() {
    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}
</script>
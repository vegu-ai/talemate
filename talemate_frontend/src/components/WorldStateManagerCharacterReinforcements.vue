<template>
    <v-row floating color="grey-darken-5">
        <v-col cols="3">
            <v-text-field v-model="search"
                label="Filter states" append-inner-icon="mdi-magnify"
                clearable density="compact" variant="underlined"
                class="ml-1 mb-1 mt-1"
                @update:modelValue="autoSelect"></v-text-field>

        </v-col>
        <v-col cols="3"></v-col>
        <v-col cols="2"></v-col>
        <v-col cols="4">
            <v-text-field v-model="newQuestion"
                label="New state" append-inner-icon="mdi-plus"
                class="mr-1 mb-1 mt-1" variant="underlined" density="compact"
                @keyup.enter="handleNew"
                hint="Question or detail name."></v-text-field>
        </v-col>
    </v-row>
    <v-divider></v-divider>
    <v-row>
        <v-col cols="4">
            <v-list density="compact">

                <!-- add from template -->
                <div v-if="templatesAvailable()">
                    <v-list-item density="compact"
                        @click.stop="showTemplates = !showTemplates"
                        prepend-icon="mdi-cube-scan" color="info">
                        <v-list-item-title>
                            Templates
                            <v-progress-circular class="ml-1 mr-3" size="14"
                                indeterminate="disable-shrink" color="primary"
                                v-if="templateBusy"></v-progress-circular>
                        </v-list-item-title>
                    </v-list-item>
                    <div v-if="showTemplates">
                        <v-list-item density="compact"
                            @click.stop="addFromTemplate(template, character.name)"
                            v-for="(template, index) in viableTemplates"
                            :key="index" prepend-icon="mdi-cube-scan"
                            :disabled="templateBusy">
                            <v-list-item-title>{{ template.name
                            }}</v-list-item-title>
                            <v-list-item-subtitle>{{ template.description
                            }}</v-list-item-subtitle>
                        </v-list-item>
                    </div>
                    <v-divider></v-divider>
                </div>

            </v-list>
            <v-tabs v-model="selected" direction="vertical" color="indigo-lighten-3" density="compact">
                <v-tab v-for="(value, detail) in filteredList"
                    :key="detail"
                    class="text-caption"
                    :value="detail">
                    <div class="text-left">{{ detail }}<div><v-chip size="x-small" label variant="outlined"
                            color="info">update in {{ value.due }}
                            turns</v-chip>
                        </div>
                    </div>
                </v-tab>
            </v-tabs>
        </v-col>
        <v-col cols="8">
            <div v-if="selected && character.reinforcements[selected] !== undefined">
                <v-textarea rows="5" auto-grow max-rows="15"
                    :label="selected"
                    :disabled="working"
                    v-model="character.reinforcements[selected].answer"
                    @update:modelValue="queueUpdate(selected)"
                    :color="dirty ? 'info' : ''"></v-textarea>

                <v-row>
                    <v-col cols="6">
                        <v-text-field
                            v-model="character.reinforcements[selected].interval"
                            label="Re-inforce / Update detail every N turns"
                            type="number" min="1" max="100" step="1"
                            :disabled="working"
                            class="mb-2"
                            @update:modelValue="queueUpdate(selected)"
                            :color="dirty ? 'info' : ''"></v-text-field>
                    </v-col>
                    <v-col cols="6">
                        <v-select
                            v-model="character.reinforcements[selected].insert"
                            :items="insertionModes"
                            :disabled="working"
                            label="Context Attachment Method"
                            class="mr-1 mb-1" variant="underlined"
                            density="compact"
                            @update:modelValue="queueUpdate(selected)"
                            :color="dirty ? 'info' : ''">
                        </v-select>
                    </v-col>
                </v-row>



                <v-textarea rows="3" auto-grow max-rows="5"
                    label="Additional instructions to the AI for generating this state."
                    v-model="character.reinforcements[selected].instructions"
                    @update:modelValue="queueUpdate(selected)"
                    :disabled="working"
                    :color="dirty ? 'info' : ''"
                    ></v-textarea>

                <v-row>
                    <v-col cols="6">
                        <div
                            v-if="removeConfirm === false">
                            <v-btn rounded="sm" prepend-icon="mdi-close-box-outline"
                                color="error" variant="text"
                                :disabled="working"
                                @click.stop="removeConfirm = true">
                                Remove state
                            </v-btn>
                        </div>
                        <div v-else>
                            <v-btn rounded="sm" prepend-icon="mdi-close-box-outline"
                                @click.stop="remove(selected)"
                                :disabled="working"
                                color="error" variant="text">
                                Confirm removal
                            </v-btn>
                            <v-btn class="ml-1" rounded="sm"
                                prepend-icon="mdi-cancel"
                                @click.stop="removeConfirm = false"
                                :disabled="working"
                                color="info" variant="text">
                                Cancel
                            </v-btn>
                        </div>
                    </v-col>
                    <v-col cols="6" class="text-right flex">
                        <v-btn rounded="sm" prepend-icon="mdi-refresh"
                            @click.stop="run(selected)"
                            :disabled="working"
                            color="primary" variant="text">
                            Refresh State
                        </v-btn>
                        <v-tooltip
                            text="Removes all previously generated reinforcements for this state and then regenerates it">
                            <template v-slot:activator="{ props }">
                                <v-btn
                                    v-if="resetConfirm === true"
                                    v-bind="props" rounded="sm"
                                    prepend-icon="mdi-backup-restore"
                                    @click.stop="run(selected, true)"
                                    :disabled="working"
                                    color="warning" variant="text">
                                    Confirm Reset State
                                </v-btn>
                                <v-btn v-else v-bind="props" rounded="sm"
                                    prepend-icon="mdi-backup-restore"
                                    @click.stop="resetConfirm = true"
                                    :disabled="working"
                                    color="warning" variant="text">
                                    Reset State
                                </v-btn>
                            </template>
                        </v-tooltip>
                    </v-col>
                </v-row>
            </div>
        </v-col>
    </v-row>
</template>
<script>

export default {
    name: "WorldStateManagerCharacterReinforcements",
    components: {
    },
    props: {
        immutableCharacter: Object,
        templates: Object,
    },
    data() {
        return {
            selected: null,
            newQuestion: null,
            newValue: null,
            removeConfirm: false,
            resetConfirm: false,
            search: null,
            dirty: false,
            busy: false,
            templateBusy: false,
            updateTimeout: null,
            character: null,
            showTemplates: false,
            newReinforcment: {
                interval: 10,
                instructions: '',
                insert: "sequential",
            }
        }
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
        'insertionModes',
    ],
    emits:[
        'require-scene-save'
    ],
    watch: {
        immutableCharacter: {
            immediate: true,
            handler(value) {
                if(value && this.character && value.name !== this.character.name) {
                    this.selected = null;
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
        working() {
            return (this.busy || this.templateBusy)
        },
        viableTemplates() {
            return Object.values(this.templates.state_reinforcement).filter(template => {
                return template.state_type == "character" || template.state_type == "npc" || template.state_type == "player";
            });
        },
        filteredList() {
            if(!this.character) {
                return {};
            }

            if (!this.search) {
                return this.character.reinforcements;
            }

            let filtered = {};
            for (let detail in this.character.reinforcements) {
                if (detail.toLowerCase().includes(this.search.toLowerCase()) || detail === this.selected) {
                    filtered[detail] = this.character.reinforcements[detail];
                }
            }
            return filtered;
        },
    },
    methods: {
        templatesAvailable() {
            for (let template in this.templates.state_reinforcement) {
                if (this.templates.state_reinforcement[template].state_type == "character" || this.templates.state_reinforcement[template].state_type == "npc" || this.templates.state_reinforcement[template].state_type == "player") {
                    return true;
                }
            }
        },

        addFromTemplate(template, characterName) {
            this.templateBusy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'interact',
                text: '!apply_world_state_template:' + template.name + ':state_reinforcement:' + characterName,
            }));
        },


        autoSelect() {
            this.selected = null
            // if there is only one detail in the filtered list, select it
            if (Object.keys(this.filteredList).length > 0) {
                this.selected = Object.keys(this.filteredList)[0];
            }
        },

        loadWithRequire(name) {
            if (this.character.reinforcements[name]) {
                this.selected = name;
            } else {
                this.add(name);
                this.update(name, true);
                this.selected = name;
            }
        },

        handleNew() {
            this.add(this.newQuestion);
            this.update(this.newQuestion, true);
            this.selected = this.newQuestion;
            this.newQuestion = null;
        },

        add(name) {
            this.character.reinforcements[name] = {...this.newReinforcment};
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

        update(name, updateState) {
            let interval = this.character.reinforcements[name].interval;
            let instructions = this.character.reinforcements[name].instructions;
            let insert = this.character.reinforcements[name].insert;
            if (updateState === true)
                this.busy = true;
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'set_character_detail_reinforcement',
                name: this.character.name,
                question: name,
                interval: interval,
                instructions: instructions,
                answer: this.character.reinforcements[name].answer,
                update_state: updateState,
                insert: insert,
            }));
        },

        remove(name) {
            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'delete_character_detail_reinforcement',
                name: this.character.name,
                question: name,
            }));

            if (this.character.reinforcements[name])
                delete this.character.reinforcements[name];

            this.removeConfirm = false;

            // select first detail
            if (this.selected == name)
                this.selected = Object.keys(this.character.reinforcements)[0];
        },

        run(name, reset) {
            this.busy = true;

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'run_character_detail_reinforcement',
                name: this.character.name,
                question: name,
                reset: reset || false,
            }));

            this.resetConfirm = false;
        },

        handleMessage(message) {

            if (message.type === 'status' && message.status === 'success' && message.message === 'Auto state added.') {
                console.log("auto state added", message);
                if (message.data.reinforcement) {
                    this.character.reinforcements[message.data.reinforcement.question] = message.data.reinforcement;
                    this.selected = message.data.reinforcement.question;
                }

                this.templateBusy = false;
                return;
            }


            if (message.type !== 'world_state_manager') {
                return;
            }


            if (message.action === 'character_detail_reinforcement_set') {
                this.dirty = false;
                this.busy = false;
                this.$emit('require-scene-save');
            }
            else if (message.action === 'character_detail_reinforcement_run') {
                this.dirty = false;
                this.busy = false;
                this.$emit('require-scene-save');
            }
            else if (message.action === 'character_detail_reinforcement_deleted') {
                this.$emit('require-scene-save');
            }
        }

    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}

</script>
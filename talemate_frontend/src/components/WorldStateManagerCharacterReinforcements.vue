<template>
    <v-row floating color="grey-darken-5">
        <v-col cols="3">
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
        <v-col cols="5">

            <v-list density="compact" slim v-model:opened="groupsOpen">
                <v-list-group value="templates" fluid>
                    <template v-slot:activator="{ props }">
                        <v-list-item  prepend-icon="mdi-cube-scan" v-bind="props">Templates</v-list-item>
                    </template>
                    <v-list-item>
                        <WorldStateManagerTemplateApplicator
                        ref="templateApplicator"
                        :validateTemplate="validateTemplate"
                        :templates="templates"
                        :source="source"
                        :template-types="['state_reinforcement']"
                        @apply-selected="applyTemplates"
                        @done="applyTemplatesDone"
                    />
                    </v-list-item>
                </v-list-group>
            </v-list>
            <v-text-field v-model="search" v-if="filteredList.length > 10"
                label="Filter" append-inner-icon="mdi-magnify"
                clearable density="compact" variant="underlined"
                class="ml-1 mb-1 mt-1"
                @update:modelValue="autoSelect"></v-text-field>
            <v-tabs :disabled="busy" v-model="selected" direction="vertical" color="indigo-lighten-3" density="compact">
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
        <v-col cols="7">
            <div v-if="selected && character.reinforcements[selected] !== undefined">
                <v-textarea rows="5" auto-grow max-rows="15"
                    :label="selected"
                    :disabled="working"
                    v-model="character.reinforcements[selected].answer"
                    @update:modelValue="queueUpdate(selected)"
                    :color="dirty ? 'dirty' : ''">
                </v-textarea>

                <v-row>
                    <v-col cols="6">
                        <v-text-field
                            v-model="character.reinforcements[selected].interval"
                            label="Re-inforce / Update detail every N turns"
                            type="number" min="1" max="100" step="1"
                            :disabled="working"
                            class="mb-2"
                            @update:modelValue="queueUpdate(selected)"
                            :color="dirty ? 'dirty' : ''"></v-text-field>
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
                            :color="dirty ? 'dirty' : ''">
                        </v-select>
                    </v-col>
                </v-row>



                <v-textarea rows="3" auto-grow max-rows="5"
                    label="Additional instructions to the AI for generating this state."
                    v-model="character.reinforcements[selected].instructions"
                    @update:modelValue="queueUpdate(selected)"
                    :disabled="working"
                    :color="dirty ? 'dirty' : ''"
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

import WorldStateManagerTemplateApplicator from './WorldStateManagerTemplateApplicator.vue';

export default {
    name: "WorldStateManagerCharacterReinforcements",
    components: {
        WorldStateManagerTemplateApplicator,
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
            updateTimeout: null,
            character: null,
            showTemplates: false,
            groupsOpen: ["states"],
            templateApplicatorCallback: null,
            source: "wsm.character_reinforcements",
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
        'toLabel',
        'formatWorldStateTemplateString',
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
            return (this.busy || this.templateApplicatorCallback !== null)
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

        applyTemplates(templateUIDs, callback) {
            this.templateApplicatorCallback = callback;

            this.busy = true;

            // collect templates

            let templates = [];

            for (let group of this.templates.managed.groups) {
                for (let templateId in group.templates) {
                    let template = group.templates[templateId];
                    if(templateUIDs.includes(template.uid)) {
                        templates.push(template);
                    }
                }
            }

            this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'apply_templates',
                templates: templates,
                run_immediately: true,
                character_name: this.character.name,
                source: this.source,
            }));
        },

        applyTemplatesDone() {
            this.busy = false;
        },


        validateTemplate(template) {
            if (template.template_type !== 'state_reinforcement') {
                return false;
            }

            const formattedQuery = this.formatWorldStateTemplateString(template.query, this.character.name);

            if(this.character.reinforcements[formattedQuery]) {
                return false;
            }

            let validStateTypes = ["character"];

            if(this.character.is_player) {
                validStateTypes.push("player");
            } else{
                validStateTypes.push("npc");
            }

            if (validStateTypes.includes(template.state_type)) {
                return true;
            }

            return false;
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

        queueUpdate(name, delay = 1500) {
            if (this.updateTimeout !== null) {
                clearTimeout(this.updateTimeout);
            }

            this.dirty = true;

            this.updateTimeout = setTimeout(() => {
                this.update(name);
            }, delay);
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

            if (message.type !== 'world_state_manager') {
                return;
            } 
            else if (message.action === 'character_detail_reinforcement_set') {
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
            else if (message.action === 'template_applied' && message.source === this.source){
                
                if(this.templateApplicatorCallback && message.status === 'done') {
                    this.templateApplicatorCallback();
                    this.templateApplicatorCallback = null;
                }

                if(message.result && message.result.character === this.character.name){
                    this.character.reinforcements[message.result.question] = message.result;
                    this.selected = message.result.question;
                }
            }
            else if (message.action === 'templates_applied' && message.source === this.source) {
                if(this.templateApplicatorCallback) {
                    this.templateApplicatorCallback();
                    this.templateApplicatorCallback = null;
                }
            }
        }

    },
    created() {
        this.registerMessageHandler(this.handleMessage);
    }
}

</script>
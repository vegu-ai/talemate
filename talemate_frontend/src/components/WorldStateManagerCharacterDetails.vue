<template>
    <v-row floating color="grey-darken-5">
        <v-col cols="3">

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
                        :template-types="['character_detail']"
                        @apply-selected="applyTemplates"
                        @done="applyTemplatesDone"
                    />
                    </v-list-item>
                </v-list-group>
            </v-list>
            <v-text-field v-model="search" v-if="Object.keys(this.character.details).length > 10"
            label="Filter details" append-inner-icon="mdi-magnify"
            clearable density="compact" variant="underlined"
            class="ml-1 mb-1 mt-1"
            @update:model-value="autoSelect"></v-text-field>
            <v-tabs :disabled="busy" direction="vertical" density="compact" v-model="selected" color="indigo-lighten-3">
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
                    ref="contextualGenerate"
                    uid="wsm.character_detail"
                    :context="'character detail:'+selected" 

                    :original="character.details[selected]"
                    :character="character.name"
                    :templates="templates"
                    :generationOptions="generationOptions"

                    @generate="content => setAndUpdate(selected, content)"
                />


                <v-textarea rows="5" max-rows="18" auto-grow
                    ref="detail"
                    :label="selected"
                    :color="dirty ? 'dirty' : ''"

                    :disabled="busy"
                    :loading="busy"
                    :hint="autocompleteInfoMessage(busy)"

                    @keyup.ctrl.enter.stop="sendAutocompleteRequest"

                    @update:modelValue="queueUpdate(selected)"

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
    <SpiceAppliedNotification :uids="['wsm.character_detail']"></SpiceAppliedNotification>

</template>

<script>
import ContextualGenerate from './ContextualGenerate.vue';
import WorldStateManagerTemplateApplicator from './WorldStateManagerTemplateApplicator.vue';
import SpiceAppliedNotification from './SpiceAppliedNotification.vue';

export default {
    name: 'WorldStateManagerCharacterDetails',
    components: {
        ContextualGenerate,
        WorldStateManagerTemplateApplicator,
        SpiceAppliedNotification,
    },
    props: {
        immutableCharacter: Object,
        templates: Object,
        generationOptions: Object,
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
            groupsOpen: [],
            templateApplicatorCallback: null,
            source: "wsm.character_details",
        }
    },
    inject: [
        'getWebsocket',
        'autocompleteInfoMessage',
        'autocompleteRequest',
        'registerMessageHandler',
        'unregisterMessageHandler',
        'formatWorldStateTemplateString',
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
                generation_options: this.generationOptions,
            }));
        },
        
        applyTemplatesDone() {
            this.busy = false;
        },

        validateTemplate(template) {
            if(template.template_type !== 'character_detail')
                return false;
            const formattedDetail = this.formatWorldStateTemplateString(template.detail, this.character.name);

            if(this.character.details[formattedDetail]) {
                return false;
            }

            return true;
        },

        autoSelect() {
            this.selected = null;
            // if there is only one detail in the filtered list, select it
            if (Object.keys(this.filteredList).length > 0) {
                this.selected = Object.keys(this.filteredList)[0];
            }
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

        update(name) {

            // if field is currently empty, don't send update, because that
            // will cause a deletion
            if (this.character.details[name] === "") {
                return;
            }

            // if value == "$DELETE", blank it out
            if (this.character.details[name] === "$DELETE") {
                this.character.details[name] = "";
            }

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
            this.character.details[name] = "$DELETE";
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
            
            else if (message.action === 'character_detail_updated') {
                this.dirty = false;
                this.$emit('require-scene-save');
            }
            else if (message.action === 'character_detail_deleted') {
                if(message.data.name === this.selected) {
                    this.selected = null;
                }
                this.$emit('require-scene-save');
            }
            else if (message.action === 'template_applied' && message.source === this.source){
                
                if(this.templateApplicatorCallback && message.status === 'done') {
                    this.templateApplicatorCallback();
                    this.templateApplicatorCallback = null;
                }

                if(message.result && message.result.character === this.character.name){
                    let detail = message.result.detail;
                    this.character.details[detail] = message.result.value;
                    this.selected = detail;
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
    mounted() {
        this.registerMessageHandler(this.handleMessage);
    },
    unmounted() {
        this.unregisterMessageHandler(this.handleMessage);
    }
}
</script>
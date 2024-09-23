<template>
    <v-row floating color="grey-darken-5">
        <v-col cols="3">
        </v-col>
        <v-col cols="3"></v-col>
        <v-col cols="2"></v-col>
        <v-col cols="4">
            <v-text-field v-model="newName"
                label="New attribute" append-inner-icon="mdi-plus"
                class="mr-1 mb-1 mt-1" variant="underlined" density="compact"
                @keyup.enter="handleNew"
                hint="Attribute name"></v-text-field>

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
                        :template-types="['character_attribute']"
                        @apply-selected="applyTemplates"
                        @done="applyTemplatesDone"
                    />
                    </v-list-item>
                </v-list-group>
            </v-list>
            <v-text-field v-model="search" v-if="Object.keys(this.character.base_attributes).length > 10"
                label="Filter" append-inner-icon="mdi-magnify"
                clearable density="compact" variant="underlined"
                clear-icon="mdi-close"
                class="ml-1 mb-1 mt-1"
                @update:modelValue="autoSelect"></v-text-field>
            <v-tabs :disabled="busy" v-model="selected" density="compact" direction="vertical" color="indigo-lighten-3">
                <v-tab density="compact" v-for="(value, attribute) in filteredList"
                class="text-caption"
                    :key="attribute" 
                    :value="attribute">
                    {{ attribute }}
                </v-tab>
            </v-tabs>

        </v-col>
        <v-col cols="8">
            <div v-if="selected !== null && character !== null && character.base_attributes[selected] !== undefined">

                <ContextualGenerate 
                    ref="contextualGenerate"
                    uid="wsm.character_attribute"
                    :context="'character attribute:'+selected" 

                    :original="character.base_attributes[selected]"
                    :character="character.name"
                    :templates="templates"
                    :generationOptions="generationOptions"

                    @generate="content => setAndUpdate(selected, content)"
                />

                <v-textarea ref="attribute" rows="5" auto-grow
                    :label="selected"
                    :color="dirty ? 'dirty' : ''"

                    :disabled="busy"
                    :loading="busy"
                    
                    :hint="autocompleteInfoMessage(busy)"
                    @keyup.ctrl.enter.stop="sendAutocompleteRequest"

                    @update:modelValue="queueUpdate(selected)"

                    v-model="character.base_attributes[selected]">
                </v-textarea>

            </div>
            <v-row v-if="selected !== null &&  character !== null && character.base_attributes[selected] !== undefined">
                <v-col cols="12">
                    <v-btn v-if="removeConfirm === false"
                        rounded="sm" prepend-icon="mdi-close-box-outline" color="error"
                        variant="text"
                        @click.stop="removeConfirm = true">
                        Remove attribute
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
            </v-row>
        </v-col>
    </v-row>
    <SpiceAppliedNotification :uids="['wsm.character_attribute']"></SpiceAppliedNotification>
</template>
<script>

import ContextualGenerate from './ContextualGenerate.vue';
import WorldStateManagerTemplateApplicator from './WorldStateManagerTemplateApplicator.vue';
import SpiceAppliedNotification from './SpiceAppliedNotification.vue';

export default {
    name: 'WorldStateManagerCharacterAttributes',
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
            source: "wsm.character_attributes",
            templateApplicatorCallback: null,
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
        'require-scene-save'
    ],
    watch: {
        immutableCharacter: {
            immediate: true,
            handler(value) {
                if(value && this.character && value.name !== this.character.name) {
                    this.character = null;
                    this.selected = null;
                }
                if (!value) {
                    this.selected = null;
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
                return this.character.base_attributes;
            }

            let filtered = {};
            for (let attribute in this.character.base_attributes) {
                if (attribute.toLowerCase().includes(this.search.toLowerCase()) || attribute === this.selected) {
                    filtered[attribute] = this.character.base_attributes[attribute];
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
                generation_options: this.generationOptions,
            }));
        },

        applyTemplatesDone() {
            this.busy = false;
        },
        
        validateTemplate(template) {
            if(template.template_type !== 'character_attribute')
                return false;
            const formattedName = this.formatWorldStateTemplateString(template.attribute, this.character.name);

            if(this.character.base_attributes[formattedName]) {
                return false;
            }

            return true;
        },

        reset() {
            this.selected = null;
            this.character = null;
            this.templateApplicatorCallback = null;
            this.groupsOpen = [];
        },

        autoSelect() {
            this.selected = null;
            // if there is only one attribute in the filtered list, select it
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
            return this.getWebsocket().send(JSON.stringify({
                type: 'world_state_manager',
                action: 'update_character_attribute',
                name: this.character.name,
                attribute: name,
                value: this.character.base_attributes[name],
            }));
        },

        setAndUpdate(name, value) {
            this.character.base_attributes[name] = value;
            this.update(name);
        },

        handleNew() {
            this.character.base_attributes[this.newName] = "";
            this.selected = this.newName;
            this.newName = null;
            // set focus to the new attribute
            this.$nextTick(() => {
                this.$refs.attribute.focus();
            });
        },

        remove(name) {
            // set value to blank
            this.character.base_attributes[name] = "";
            this.removeConfirm = false;
            // send update
            this.update(name);
            // remove attribute from list
            delete this.character.base_attributes[name];
            this.selected = null;
        },

        sendAutocompleteRequest() {
            this.busy = true;
            this.autocompleteRequest({
                partial: this.character.base_attributes[this.selected],
                context: `character attribute:${this.selected}`,
                character: this.character.name
            }, (completion) => {
                this.character.base_attributes[this.selected] += completion;
                this.busy = false;
            }, this.$refs.attribute);

        },
        
        handleMessage(message) {
            if (message.type !== 'world_state_manager') {
                return;
            }

            
            if (message.action === 'character_attribute_updated') {
                this.dirty = false;
                this.$emit('require-scene-save');
            }
            else if (message.action === 'operation_done') {
                this.busy = false;
            }
            else if (message.action === 'template_applied' && message.source === this.source){
                
                if(this.templateApplicatorCallback && message.status === 'done') {
                    this.templateApplicatorCallback();
                    this.templateApplicatorCallback = null;
                }

                if(message.result && message.result.character === this.character.name){
                    let attributeName = message.result.attribute;
                    this.character.base_attributes[attributeName] = message.result.value;
                    this.selected = attributeName;
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
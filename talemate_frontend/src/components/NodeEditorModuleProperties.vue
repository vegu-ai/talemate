<template>
    <div v-if="hasEditableProperties">
        <v-toolbar color="mutedbg" density="compact">
            <v-toolbar-title><v-icon color="primary">mdi-card-bulleted-settings</v-icon> Module Properties</v-toolbar-title>
        </v-toolbar>

        <v-list style="overflow-y: auto;" density="compact">
            <v-list-item v-for="prop, name in editableProperties" :key="name">
                <v-checkbox v-if="prop.type === 'bool'" v-model="properties[name]" :label="prop.description" @update:model-value="updateProperty(name, properties[name])" color="primary" density="compact"></v-checkbox>
                <div v-else-if="prop.type === 'icon'">
                    <div class="text-caption text-muted mb-1">{{ prop.description }}</div>
                    <IconPicker :model-value="iconValue(name)" @update:model-value="updateIcon(name, $event)" @update:valid="iconValid[name] = $event" />
                </div>
                <v-textarea v-else-if="prop.type === 'text'" v-model="properties[name]" :label="prop.description" @blur="updateProperty(name, properties[name])" color="primary" rows="3" auto-grow></v-textarea>
                <v-text-field v-else v-model="properties[name]" :label="prop.description" @blur="updateProperty(name, properties[name])" color="primary" dense></v-text-field>
            </v-list-item>
        </v-list>
    </div>
</template>

<script>

import IconPicker from './IconPicker.vue';
import { EDITABLE_MODULE_PROPERTY_TYPES } from '@/utils/moduleProperties';

export default {
    name: 'NodeEditorModuleProperties',
    components: {
        IconPicker,
    },
    props: {
        module: Object
    },
    emits: ['update'],
    watch: {
        module: {
            handler: function() {
                if(this.module && this.module.talemateProperties) {
                    // Deep clone to avoid mutating graph or triggering upstream watchers
                    this.properties = JSON.parse(JSON.stringify(this.module.talemateProperties));
                    this.fields = JSON.parse(JSON.stringify(this.module.talemateFields || {}));
                    this.iconDrafts = {};
                }
            },
            deep: true,
            immediate: true
        }
    },
    computed: {
        hasEditableProperties: function() {
            return Object.keys(this.editableProperties).length > 0;
        },
        editableProperties: function() {
            let editable = {};
            for(let key in this.fields) {
                if(EDITABLE_MODULE_PROPERTY_TYPES.includes(this.fields[key].type)) {
                    editable[key] = {
                        "value": this.properties[key],
                        "type": this.fields[key].type,
                        "description": this.fields[key].description
                    }
                }
            }
            return editable;
        }
    },
    data: function() {
        return {
            properties: {},
            fields: {},
            iconValid: {},
            iconDrafts: {},
        }
    },
    methods: {
        iconValue: function(name) {
            if(name in this.iconDrafts) {
                return this.iconDrafts[name];
            }
            return this.properties[name] || '';
        },
        updateIcon: function(name, value) {
            // an invalid icon stays a draft so it never reaches the properties
            // object that any other field's edit emits upward
            this.iconDrafts[name] = value;
            // the picker reports validity through an event, so it only settles
            // once the new value has been handed back down to it
            this.$nextTick(() => {
                if(this.iconValid[name]) {
                    this.updateProperty(name, value);
                }
            });
        },
        updateProperty: function(name, value) {
            this.properties[name] = value;
            this.$emit('update', this.properties);
        }
    }   
}

</script>

<style scoped>
</style>
<template>
    <div v-if="hasEditableProperties">
        <v-toolbar color="mutedbg" density="compact">
            <v-toolbar-title><v-icon color="primary">mdi-card-bulleted-settings</v-icon> Module Properties</v-toolbar-title>
        </v-toolbar>

        <v-list style="overflow-y: auto;" density="compact">
            <v-list-item v-for="prop, name in editableProperties" :key="name">
                <v-checkbox v-if="prop.type === 'bool'" v-model="prop.value" :label="prop.description" @blur="updateProperty(name, prop.value)" color="primary" density="compact"></v-checkbox>
                <v-textarea v-else-if="prop.type === 'text'" v-model="prop.value" :label="prop.description" @blur="updateProperty(name, prop.value)" color="primary" rows="3" auto-grow></v-textarea>
                <v-text-field v-else v-model="prop.value" :label="prop.description" @blur="updateProperty(name, prop.value)" color="primary" dense></v-text-field>
            </v-list-item>
        </v-list>
    </div>
</template>

<script>

export default {
    name: 'NodeEditorModuleProperties',
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
                if(this.editableTypes.includes(this.fields[key].type)) {
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
            editableTypes: [
                "str",
                "color",
                "int",
                "float",
                "bool",
                "text",
            ]
        }
    },
    methods: {
        updateProperty: function(name, value) {
            this.properties[name] = value;
            this.$emit('update', this.properties);
        }
    }   
}

</script>

<style scoped>
</style>
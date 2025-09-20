<template>
    <v-card v-if="hasEditableProperties" class="ma-0 sticky-left" :width="expanded ? 600 : 125" ref="container" elevation="7">
        <v-list max-height="720" style="overflow-y: auto;" density="compact">
            <v-row no-gutters>
                <v-col :cols="12" class="text-right">
                    <v-btn color="primary" variant="text" size="small" @click="expanded = !expanded" :prepend-icon="expanded ? 'mdi-menu-up' : 'mdi-menu-down'" text>Properties</v-btn>
                </v-col>
            </v-row>   
            
            <div v-if="expanded === true">
                <v-list-item v-for="prop, name in editableProperties" :key="name">
                    <v-checkbox v-if="prop.type === 'bool'" v-model="prop.value" :label="prop.description" @blur="updateProperty(name, prop.value)" color="primary" density="compact"></v-checkbox>
                    <v-textarea v-else-if="prop.type === 'text'" v-model="prop.value" :label="prop.description" @blur="updateProperty(name, prop.value)" color="primary" rows="3" auto-grow></v-textarea>
                    <v-text-field v-else v-model="prop.value" :label="prop.description" @blur="updateProperty(name, prop.value)" color="primary" dense></v-text-field>
                </v-list-item>

            </div>
        </v-list>

    </v-card>
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
            expanded: false,
            properties: {},
            fields: {},
            editableTypes: [
                "str",
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

.sticky-left {
    position: absolute;
    left: 0px;
    top: 50px;
    width: 400px;
    z-index: 10;
}

</style>
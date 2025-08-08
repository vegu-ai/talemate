<template>

    <div>
        <div class="text-caption text-muted" v-if="label">
            <strong>{{ label }}</strong>
        </div>
        <v-alert color="muted" variant="text" v-if="description">
            {{ description }}
        </v-alert>
        <v-table>
            <thead>
                <tr>
                    <th v-for="column in columns" :key="column.name">{{ column.label }}</th>
                    <!-- Add an extra header column for row actions when deletion is allowed -->
                    <th v-if="allow_delete" style="width:40px"></th>
                </tr>
            </thead>
            <tbody>
                <tr v-for="(value, index) in values" :key="index">
                    <td v-for="column in columns" :key="column.name">
                        <ConfigWidgetField 
                            v-model="values[index][column.name]" 
                            @update:modelValue="save(index, column.name, $event)"
                            :name="column.name" 
                            :default="value[column.name]" 
                            :type="column.type" 
                            :label="column.label" 
                            :description="column.description" 
                            :choices="column.choices" 
                            :max="column.max" :min="column.min" :step="column.step" />
                    </td>
                    <!-- Delete button -->
                    <td v-if="allow_delete">
                        <v-btn icon density="comfortable" variant="text" color="delete" @click="removeRow(index)">
                            <v-icon size="small">mdi-close-circle</v-icon>
                        </v-btn>
                    </td>
                </tr>
            </tbody>
        </v-table>

        <!-- Add button -->
        <v-btn v-if="allow_add" class="mt-2" color="primary" variant="outlined" @click="addRow">
            <v-icon start>mdi-plus</v-icon>
            Add
        </v-btn>
    </div>

</template>
<script>

import ConfigWidgetField from './ConfigWidgetField.vue'

export default {
    props: {
        label: {
            type: String,
            required: false
        },
        description: {
            type: String,
            required: false
        },
        columns: {
            type: Array,
            required: true
        },
        default_values: {
            type: Array,
            required: true
        },
        allow_add: {
            type: Boolean,
            required: false,
            default: true
        },
        allow_delete: {
            type: Boolean,
            required: false,
            default: true
        }
    },
    data() {
        return {
            values: this.default_values
        }
    },
    components: {
        ConfigWidgetField
    },
    emits: [
        "save"
    ],
    methods: {
        save(row, field, value) {
            this.values[row][field] = value
            this.$emit("save", this.values)
        },
        // Add a new empty row, using sensible defaults per column type
        addRow() {
            const newRow = {}
            this.columns.forEach(col => {
                if (col.default !== undefined) {
                    newRow[col.name] = col.default
                } else {
                    // fallback based on type
                    switch (col.type) {
                        case 'number':
                            newRow[col.name] = col.min !== undefined ? col.min : 0
                            break
                        case 'bool':
                            newRow[col.name] = false
                            break
                        case 'flags':
                            newRow[col.name] = []
                            break
                        default:
                            newRow[col.name] = ''
                    }
                }
            })
            this.values.push(newRow)
            this.$emit("save", this.values)
        },
        // Remove the row at the specified index
        removeRow(index) {
            this.values.splice(index, 1)
            this.$emit("save", this.values)
        }
    }
}
</script>
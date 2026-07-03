<template>

    <div>
        <div class="text-caption text-muted" v-if="label">
            <strong>{{ label }}</strong>
        </div>
        <v-alert color="muted" variant="text" v-if="description">
            {{ description }}
        </v-alert>

        <!-- Preset insert: appends editable copies of the selected preset's rows -->
        <div v-if="allow_add && presets && presets.length" class="d-flex align-center mb-4" style="max-width: 480px;">
            <v-select
                v-model="selectedPreset"
                :items="presets"
                item-title="label"
                return-object
                density="compact"
                label="Preset"
                hide-details
                class="mr-2"
            ></v-select>
            <v-btn color="primary" variant="outlined" :disabled="!selectedPreset" @click="insertPreset">
                <v-icon start>mdi-tray-arrow-down</v-icon>
                Insert
            </v-btn>
        </div>
        <!-- Each row renders as a stacked card so wide column sets don't get
             squished into table cells (this widget lives inside modals and
             narrow editor panes). -->
        <!-- no color prop: on an outlined card it would tint the whole
             card text (inputs included), not just the border -->
        <v-card v-for="(value, index) in values" :key="index" variant="outlined" class="mb-3">
            <!-- fields grid plus a slim vertical control rail on the right,
                 so row controls don't cost a full row of vertical space -->
            <div class="d-flex">
                <v-card-text class="pb-2 flex-grow-1">
                    <v-row dense>
                        <v-col v-for="column in visibleColumns(values[index])" :key="column.name" cols="12" :sm="(column.span || defaultSpan(column)) >= 12 ? 12 : 6" :md="column.span || defaultSpan(column)">
                            <ConfigWidgetField
                                v-model="values[index][column.name]"
                                @update:modelValue="save(index, column.name, $event)"
                                :name="column.name"
                                :default="value[column.name]"
                                :type="column.type"
                                :label="columnLabel(column, values[index])"
                                :description="column.description"
                                :choices="column.choices"
                                :rows="column.rows"
                                :max-rows="column.max_rows"
                                :auto-grow="column.auto_grow"
                                density="compact"
                                :max="column.max" :min="column.min" :step="column.step" />
                        </v-col>
                    </v-row>
                </v-card-text>
                <div class="d-flex flex-column align-center pa-1">
                    <span class="text-caption text-muted">#{{ index + 1 }}</span>
                    <v-checkbox-btn
                        v-for="column in railColumns(values[index])"
                        :key="column.name"
                        v-model="values[index][column.name]"
                        @update:modelValue="save(index, column.name, $event)"
                        density="compact"
                        color="primary"
                        class="flex-grow-0"
                    ></v-checkbox-btn>
                    <template v-if="allow_reorder">
                        <v-btn icon size="small" density="compact" variant="text" :disabled="index === 0" @click="moveRow(index, -1)">
                            <v-icon>mdi-arrow-up</v-icon>
                        </v-btn>
                        <v-btn icon size="small" density="compact" variant="text" :disabled="index === values.length - 1" @click="moveRow(index, 1)">
                            <v-icon>mdi-arrow-down</v-icon>
                        </v-btn>
                    </template>
                    <v-btn v-if="allow_delete" icon size="small" density="compact" variant="text" color="delete" @click="removeRow(index)">
                        <v-icon>mdi-close-circle</v-icon>
                    </v-btn>
                </div>
            </div>
        </v-card>

        <!-- Add button -->
        <v-btn v-if="allow_add" class="mt-2" color="primary" variant="outlined" @click="addRow">
            <v-icon start>mdi-plus</v-icon>
            Add
        </v-btn>
    </div>

</template>
<script>

import { debounce } from 'lodash'
import ConfigWidgetField from './ConfigWidgetField.vue'
import { conditionMet } from '@/utils/uxConditions'

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
        },
        allow_reorder: {
            type: Boolean,
            required: false,
            default: false
        },
        // [{label, rows}] - selecting one appends copies of its rows
        presets: {
            type: Array,
            required: false,
            default: null
        },
        // echoed back as the second `save` argument. Consumers that key
        // this widget by entity need it: an unmounting instance's flush
        // still carries the entity it was editing, while the consumer's
        // own state may already point at the newly selected entity.
        saveTarget: {
            required: false,
            default: null
        }
    },
    data() {
        return {
            values: this.default_values,
            selectedPreset: null
        }
    },
    components: {
        ConfigWidgetField
    },
    emits: [
        "save"
    ],
    created() {
        // per-keystroke field edits debounce the save emission — consumers
        // like the character finalizers editor persist to the backend on
        // every save, so emitting per input event would spam websocket
        // saves. Structural ops (add/remove/move/insert) emit immediately.
        this.emitSaveDebounced = debounce(() => this.$emit("save", this.values, this.saveTarget), 600)
    },
    beforeUnmount() {
        // don't lose trailing keystrokes when the widget is torn down
        this.emitSaveDebounced.flush()
    },
    methods: {
        emitSave() {
            this.emitSaveDebounced.cancel()
            this.$emit("save", this.values, this.saveTarget)
        },
        // columns visible in the given row's fields grid — a column's
        // condition (talemate.ux.schema.Condition) resolves against sibling
        // values; rail columns render in the control rail instead
        visibleColumns(row) {
            return this.columns.filter(
                column => !column.rail && conditionMet(column.condition, row[column.condition?.attribute])
            )
        },
        // bool columns rendered in the row's control rail
        railColumns(row) {
            return this.columns.filter(
                column => column.rail && conditionMet(column.condition, row[column.condition?.attribute])
            )
        },
        // label for a column in the given row, honoring the column's
        // dynamic_label override (talemate.ux.schema.DynamicLabel)
        columnLabel(column, row) {
            const dyn = column.dynamic_label
            if (dyn && dyn.labels) {
                const override = dyn.labels[String(row[dyn.attribute])]
                if (override !== undefined) return override
            }
            return column.label
        },
        // grid width (of 12) for a column without an explicit `span`
        defaultSpan(column) {
            switch (column.type) {
                case 'bool':
                    return 2
                case 'flags':
                    return 4
                default:
                    return Array.isArray(column.choices) && column.choices.length > 0 ? 3 : 4
            }
        },
        save(row, field, value) {
            this.values[row][field] = value
            this.emitSaveDebounced()
        },
        // Add a new empty row, using sensible defaults per column type
        addRow() {
            const newRow = {}
            this.columns.forEach(col => {
                const columnDefault = col.default !== undefined ? col.default : col.default_value
                if (columnDefault !== undefined && columnDefault !== null) {
                    newRow[col.name] = columnDefault
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
            this.emitSave()
        },
        // Remove the row at the specified index
        removeRow(index) {
            this.values.splice(index, 1)
            this.emitSave()
        },
        // Append copies of the selected preset's rows
        insertPreset() {
            if (!this.selectedPreset) return
            const rows = JSON.parse(JSON.stringify(this.selectedPreset.rows || []))
            this.values.push(...rows)
            this.emitSave()
        },
        // Move the row at the specified index up (-1) or down (1)
        moveRow(index, direction) {
            const target = index + direction
            if (target < 0 || target >= this.values.length) return
            const [row] = this.values.splice(index, 1)
            this.values.splice(target, 0, row)
            this.emitSave()
        }
    }
}
</script>
<template>

    <div>
        <div class="text-subtitle-2 text-mutedheader" v-if="label">{{ label }}</div>
        <div class="text-body-2 text-muted mb-3" :class="{ 'mt-1': label }" v-if="description">{{ description }}</div>

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

        <div v-if="!values.length" class="text-caption text-muted mb-3">{{ emptyHint }}</div>

        <!-- Each row renders as a stacked card so wide column sets don't get
             squished into table cells (this widget lives inside modals and
             narrow editor panes). -->
        <!-- no color prop: on an outlined card it would tint the whole
             card text (inputs included), not just the border -->
        <v-card v-for="(value, index) in values" :key="index" variant="outlined" class="mb-3">
            <!-- slim header row: index + summary on the left, row controls on
                 the right, so controls don't cost a full row of vertical space
                 and the fields grid gets the full card width -->
            <div class="d-flex align-center px-4 pt-2">
                <span class="text-caption text-muted mr-2">#{{ index + 1 }}</span>
                <span class="text-caption text-mutedheader">{{ rowSummary(values[index]) }}</span>
                <v-spacer></v-spacer>
                <div v-for="column in railColumns(values[index])" :key="column.name" class="d-flex align-center">
                    <v-checkbox-btn
                        v-model="values[index][column.name]"
                        @update:modelValue="save(index, column.name, $event)"
                        density="compact"
                        color="primary"
                        class="flex-grow-0"
                    ></v-checkbox-btn>
                    <v-tooltip activator="parent" location="top">{{ railLabel(column) }}</v-tooltip>
                </div>
                <template v-if="allow_reorder && values.length > 1">
                    <v-btn icon size="small" density="compact" variant="text" :disabled="index === 0" @click="moveRow(index, -1)">
                        <v-icon>mdi-arrow-up</v-icon>
                        <v-tooltip activator="parent" location="top">Move up</v-tooltip>
                    </v-btn>
                    <v-btn icon size="small" density="compact" variant="text" :disabled="index === values.length - 1" @click="moveRow(index, 1)">
                        <v-icon>mdi-arrow-down</v-icon>
                        <v-tooltip activator="parent" location="top">Move down</v-tooltip>
                    </v-btn>
                </template>
                <v-btn v-if="allow_delete" icon size="small" density="compact" variant="text" color="delete" class="ml-1" @click="removeRow(index)">
                    <v-icon>mdi-close-circle</v-icon>
                    <v-tooltip activator="parent" location="top">Remove</v-tooltip>
                </v-btn>
            </div>
            <v-card-text class="pt-1 pb-2" :class="{ 'row-fields--disabled': rowDisabled(values[index]) }">
                <v-row dense>
                    <v-col v-for="column in visibleColumns(values[index])" :key="column.name" cols="12" :sm="columnSpan(column, values[index]) >= 12 ? 12 : 6" :md="columnSpan(column, values[index])">
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
        </v-card>

        <!-- Add button -->
        <v-btn v-if="allow_add" class="mt-2 mb-6" color="primary" variant="outlined" @click="addRow">
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
    computed: {
        emptyHint() {
            if (!this.allow_add) return "No entries yet."
            if (this.presets && this.presets.length) return "No entries yet — use Add to create one, or insert a preset."
            return "No entries yet — use Add to create one."
        }
    },
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
        // grid width for a column in the given row, honoring the column's
        // dynamic_span override (talemate.ux.schema.DynamicSpan)
        columnSpan(column, row) {
            const dyn = column.dynamic_span
            if (dyn && dyn.spans) {
                const override = dyn.spans[String(row[dyn.attribute])]
                if (override !== undefined) return override
            }
            return column.span || this.defaultSpan(column)
        },
        // rail columns are commonly unlabelled (the checkbox stands on its
        // own), so the tooltip falls back to a title-cased column name
        // (`enabled` -> "Enabled", `some_flag` -> "Some Flag")
        railLabel(column) {
            if (column.label) return column.label
            return column.name.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase())
        },
        // scanning aid in the row header: the selected choice labels of the
        // row's single-choice columns, e.g. "Exact match · Positive"
        rowSummary(row) {
            return this.visibleColumns(row)
                .filter(column => column.type !== 'flags' && Array.isArray(column.choices))
                .map(column => column.choices.find(choice => choice.value == row[column.name])?.label)
                .filter(Boolean)
                .join(' · ')
        },
        // an explicitly disabled row dims its fields, but keeps its controls
        // legible so it can be switched back on. The row's enable toggle is
        // whichever rail column declares `disables_row`
        // (talemate.ux.schema.Column). Values arrive loosely typed across the
        // websocket, so any present-but-falsy value dims — a missing key does
        // not, matching the backend default of enabled.
        rowDisabled(row) {
            const column = this.columns.find(c => c.rail && c.disables_row)
            if (!column) return false
            const value = row[column.name]
            return value !== undefined && !value
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
            // clear the selection so a second click can't silently duplicate
            this.selectedPreset = null
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
<style scoped>
.row-fields--disabled {
    opacity: 0.45;
}

/* outlined-variant borders are currentColor (full text brightness) since the
   cards carry no color prop — tone them down to a subtle frame */
.v-card--variant-outlined {
    border-color: rgb(var(--v-theme-card_border));
}
</style>

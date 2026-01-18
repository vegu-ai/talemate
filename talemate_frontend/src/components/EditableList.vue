<template>
    <div class="editable-list-container">
        <div v-if="modelValue.length > 0" class="editable-list-items mb-2">
            <v-card
                v-for="(item, index) in modelValue"
                :key="index"
                variant="flat"
                class="mb-0 editable-list-item"
            >
                <v-card-text class="pa-1 d-flex align-center">
                    <div class="editable-list-item-text flex-grow-1 text-caption">
                        {{ item }}
                    </div>
                    <div class="editable-list-item-actions d-flex align-center ml-1">
                        <v-btn
                            v-if="allowDuplicate"
                            icon
                            size="x-small"
                            variant="text"
                            color="primary"
                            @click="duplicateItem(index)"
                            :disabled="disabled"
                        >
                            <v-icon size="small">mdi-content-copy</v-icon>
                        </v-btn>
                        <v-btn
                            icon
                            size="x-small"
                            variant="text"
                            color="delete"
                            @click="removeItem(index)"
                            :disabled="disabled"
                        >
                            <v-icon size="small">mdi-close</v-icon>
                        </v-btn>
                    </div>
                </v-card-text>
            </v-card>
        </div>
        <v-textarea
            ref="inputField"
            v-model="inputValue"
            :label="label"
            :hint="hint"
            :placeholder="placeholder"
            :disabled="disabled"
            @keydown.ctrl.enter.prevent="addItem"
            @keydown.meta.enter.prevent="addItem"
            variant="outlined"
            density="compact"
            rows="1"
            auto-grow
        >
            <template v-slot:append-inner>
                <v-btn
                    size="small"
                    variant="text"
                    color="primary"
                    icon
                    @click="addItem"
                    :disabled="!inputValue.trim() || disabled"
                >
                    <v-icon>mdi-plus</v-icon>
                </v-btn>
            </template>
        </v-textarea>
    </div>
</template>

<script>
export default {
    name: 'EditableList',
    props: {
        modelValue: {
            type: Array,
            default: () => [],
        },
        label: {
            type: String,
            default: 'Add item',
        },
        hint: {
            type: String,
            default: 'Press Ctrl+Enter (Cmd+Enter on Mac) to add',
        },
        placeholder: {
            type: String,
            default: '',
        },
        disabled: {
            type: Boolean,
            default: false,
        },
        allowDuplicate: {
            type: Boolean,
            default: true,
        },
        prependIcon: {
            type: String,
            default: 'mdi-plus',
        },
        addButtonText: {
            type: String,
            default: 'Add',
        },
        maxHeight: {
            type: String,
            default: '300px',
        },
    },
    data() {
        return {
            inputValue: '',
        };
    },
    methods: {
        addItem() {
            const trimmed = this.inputValue.trim();
            if (trimmed && !this.disabled) {
                const newItems = [...this.modelValue, trimmed];
                this.$emit('update:modelValue', newItems);
                this.inputValue = '';
            }
        },
        removeItem(index) {
            if (!this.disabled && index >= 0 && index < this.modelValue.length) {
                const newItems = [...this.modelValue];
                newItems.splice(index, 1);
                this.$emit('update:modelValue', newItems);
            }
        },
        duplicateItem(index) {
            if (!this.disabled && index >= 0 && index < this.modelValue.length) {
                this.inputValue = this.modelValue[index];
                // Focus the textarea field after a short delay
                this.$nextTick(() => {
                    const textarea = this.$refs.inputField?.$el?.querySelector('textarea');
                    if (textarea) {
                        textarea.focus();
                    }
                });
            }
        },
    },
};
</script>

<style scoped>
.editable-list-container {
    width: 100%;
}

.editable-list-items {
    max-height: v-bind(maxHeight);
    overflow-y: auto;
}

.editable-list-item {
    transition: all 0.2s ease;
    border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.12);
    border-radius: 0;
    box-shadow: none;
}

.editable-list-item:hover {
    background-color: rgba(var(--v-theme-primary), 0.05);
}

.editable-list-item :deep(.v-card-text) {
    padding: 4px 8px !important;
}

.editable-list-item-text {
    word-wrap: break-word;
    word-break: break-word;
    white-space: pre-wrap;
    overflow-wrap: break-word;
    min-width: 0;
    line-height: 1.3;
}

.editable-list-item-actions {
    flex-shrink: 0;
}
</style>

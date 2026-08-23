<template>
    <div class="game-state-value-input">
        <template v-if="value === undefined">
            <div class="text-caption mb-1">
                <v-icon size="small" class="mr-1" color="primary">mdi-variable</v-icon>
                {{ displayLabel }}
            </div>
            <div class="text-caption text-error">Path not found in game state</div>
        </template>

        <v-text-field
            v-else-if="typeof value === 'string'"
            :model-value="draftFor(value)"
            @update:model-value="setDraft"
            @blur="commitDraft"
            :label="displayLabel"
            density="compact"
            variant="outlined"
            hide-details
            color="primary"
            :disabled="disabled"
        />

        <v-number-input
            v-else-if="typeof value === 'number'"
            :model-value="draftFor(value)"
            @update:model-value="setDraft"
            @blur="commitDraft"
            :label="displayLabel"
            density="compact"
            variant="outlined"
            hide-details
            control-variant="hidden"
            color="primary"
            :disabled="disabled"
        />

        <v-checkbox
            v-else-if="typeof value === 'boolean'"
            :model-value="value"
            @update:model-value="$emit('update-value', $event)"
            :label="displayLabel"
            density="compact"
            hide-details
            color="primary"
            :disabled="disabled"
        />

        <v-text-field
            v-else-if="value === null"
            :model-value="draftFor('')"
            @update:model-value="setDraft"
            @blur="commitDraft"
            :label="displayLabel"
            placeholder="null"
            density="compact"
            variant="outlined"
            hide-details
            color="primary"
            :disabled="disabled"
        />

        <template v-else>
            <div class="text-caption mb-1">
                <v-icon size="small" class="mr-1" color="primary">mdi-variable</v-icon>
                {{ displayLabel }}
            </div>
            <div v-if="Array.isArray(value)" class="text-caption text-medium-emphasis">
                List with {{ value.length }} items (read-only)
            </div>
            <div v-else-if="typeof value === 'object' && value !== null" class="text-caption text-medium-emphasis">
                Object with {{ Object.keys(value).length }} keys (read-only)
            </div>
            <div v-else class="text-caption text-medium-emphasis">
                {{ typeof value }} (read-only)
            </div>
        </template>

        <div
            v-if="showPathSubtitle && label"
            class="text-caption text-medium-emphasis mt-1 game-state-path-subtitle"
        >
            {{ path }}
        </div>
    </div>
</template>

<script>
export default {
    name: 'GameStateValueInput',
    props: {
        path: {
            type: String,
            required: true,
        },
        value: {
            default: undefined,
        },
        label: {
            type: String,
            default: '',
        },
        showPathSubtitle: Boolean,
        disabled: Boolean,
    },
    emits: ['update-value'],
    data() {
        return {
            draftValue: undefined,
            hasDraft: false,
        };
    },
    computed: {
        displayLabel() {
            return this.label || this.path;
        },
    },
    methods: {
        draftFor(fallbackValue) {
            return this.hasDraft ? this.draftValue : fallbackValue;
        },
        setDraft(value) {
            this.draftValue = value;
            this.hasDraft = true;
        },
        clearDraft() {
            this.hasDraft = false;
            this.draftValue = undefined;
        },
        commitDraft() {
            if (!this.hasDraft) return;

            let next = this.draftValue;
            if (typeof this.value === 'number') {
                const trimmed = typeof next === 'string' ? next.trim() : next;
                const numericValue = Number(trimmed);
                if (trimmed === '' || trimmed === null || !Number.isFinite(numericValue)) {
                    this.clearDraft();
                    return;
                }
                next = numericValue;
            } else if (this.value === null && typeof next === 'string') {
                const trimmed = next.trim();
                if (trimmed === '') {
                    this.clearDraft();
                    return;
                }
                try {
                    next = JSON.parse(trimmed);
                } catch {
                    next = trimmed;
                }
            }

            this.clearDraft();
            if (!Object.is(next, this.value)) {
                this.$emit('update-value', next);
            }
        },
    },
};
</script>

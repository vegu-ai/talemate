<template>
    <div class="game-state-value-input">
        <v-tooltip
            v-if="settings.description"
            activator="parent"
            :text="settings.description"
            location="top"
            open-delay="400"
        />

        <template v-if="value === undefined">
            <div class="text-body-small mb-1">
                <v-icon size="small" class="mr-1" color="primary">mdi-variable</v-icon>
                {{ displayLabel }}
            </div>
            <div class="text-body-small text-error">Path not found in game state</div>
        </template>

        <template v-else-if="settings.read_only">
            <div class="text-body-small mb-1">
                <v-icon size="small" class="mr-1" color="primary">mdi-lock-outline</v-icon>
                {{ displayLabel }}
            </div>
            <div class="text-body-medium">{{ readOnlyValue }}</div>
        </template>

        <template v-else-if="settingsTypeMismatch">
            <div class="text-body-small mb-1">
                <v-icon size="small" class="mr-1" color="warning">mdi-alert-outline</v-icon>
                {{ displayLabel }}
            </div>
            <div class="text-body-medium">{{ readOnlyValue }}</div>
            <div class="text-body-small text-warning">{{ settingsTypeMismatch }}</div>
        </template>

        <template v-else-if="showSlider">
            <div class="d-flex align-center ga-2 text-body-small">
                <span class="text-truncate">{{ displayLabel }}</span>
                <v-spacer />
                <span class="font-weight-medium">{{ draftFor(value) }}</span>
            </div>
            <v-slider
                :model-value="draftFor(value)"
                @update:model-value="setDraft"
                @end="commitDraft"
                @blur="commitDraft"
                :min="settings.minimum"
                :max="settings.maximum"
                :step="settings.step"
                density="compact"
                hide-details
                color="primary"
                :disabled="disabled"
            />
        </template>

        <v-select
            v-else-if="showChoices"
            :model-value="draftFor(value)"
            @update:model-value="commitValue"
            :items="settings.choices"
            :label="displayLabel"
            density="compact"
            variant="outlined"
            hide-details
            color="primary"
            :disabled="disabled"
        />

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
            :min="settings.minimum ?? undefined"
            :max="settings.maximum ?? undefined"
            :step="settings.step ?? undefined"
            :precision="numberPrecision"
            density="compact"
            variant="outlined"
            hide-details
            control-variant="hidden"
            color="primary"
            :disabled="disabled"
        />

        <v-checkbox
            v-else-if="typeof value === 'boolean'"
            :model-value="draftFor(value)"
            @update:model-value="commitValue"
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
            <div class="text-body-small mb-1">
                <v-icon size="small" class="mr-1" color="primary">mdi-variable</v-icon>
                {{ displayLabel }}
            </div>
            <div v-if="Array.isArray(value)" class="text-body-small text-medium-emphasis">
                List with {{ value.length }} items (read-only)
            </div>
            <div v-else-if="typeof value === 'object' && value !== null" class="text-body-small text-medium-emphasis">
                Object with {{ Object.keys(value).length }} keys (read-only)
            </div>
            <div v-else class="text-body-small text-medium-emphasis">
                {{ typeof value }} (read-only)
            </div>
        </template>

        <div
            v-if="showPathSubtitle && settings.label"
            class="text-body-small text-medium-emphasis mt-1 game-state-path-subtitle"
        >
            {{ path }}
        </div>
    </div>
</template>

<script>
function decimalsOf(value) {
    const text = String(value ?? '');
    if (!text || text.includes('e')) return null;
    const separator = text.indexOf('.');
    return separator === -1 ? 0 : text.length - separator - 1;
}

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
        settings: {
            type: Object,
            default: () => ({}),
        },
        showPathSubtitle: Boolean,
        disabled: Boolean,
        answer: {
            type: Object,
            default: null,
        },
        refusals: {
            type: Number,
            default: 0,
        },
    },
    emits: ['update-value'],
    data() {
        return {
            draftValue: undefined,
            hasDraft: false,
            pending: false,
        };
    },
    watch: {
        // the scene state caught up, so the prop is authoritative again
        value() {
            if (this.pending) this.clearDraft();
        },
        // the answer is queued ahead of the scene status that carries the value
        // back, so release the held value only once the prop agrees with it
        answer(next) {
            if (this.pending && next && Object.is(next.value, this.value)) {
                this.clearDraft();
            }
        },
        // a refused write leaves the prop already correct
        refusals() {
            if (this.pending) this.clearDraft();
        },
    },
    computed: {
        displayLabel() {
            return this.settings.label || this.path;
        },
        bounded() {
            return this.settings.minimum !== null && this.settings.minimum !== undefined
                && this.settings.maximum !== null && this.settings.maximum !== undefined;
        },
        showSlider() {
            return typeof this.value === 'number'
                && this.settings.slider
                && this.bounded
                && Boolean(this.settings.step);
        },
        showChoices() {
            return typeof this.value === 'string' && (this.settings.choices || []).length > 0;
        },
        settingsTypeMismatch() {
            // null, lists and dicts have editors of their own that the settings
            // do not refuse — the null field parses what is typed into it
            if (this.value === undefined || typeof this.value === 'object') return '';
            if ((this.settings.choices || []).length && typeof this.value !== 'string') {
                return 'Configured with a list of choices, but the value is not text.';
            }
            if (this.numberSettings && typeof this.value !== 'number') {
                return 'Configured as a number, but the value is not a number.';
            }
            return '';
        },
        numberPrecision() {
            // v-number-input defaults to 0 decimals, which renders a fractional
            // value as a whole one and writes that back on blur; null is its
            // "no limit". The grid starts at the minimum, so its decimals count
            // as much as the step's — the same rule as _snap and useSteps.
            if (this.settings.step === null || this.settings.step === undefined) {
                return null;
            }
            const grid = [this.settings.step, this.settings.minimum]
                .filter((bound) => bound !== null && bound !== undefined)
                .map(decimalsOf);
            return grid.includes(null) ? null : Math.max(...grid);
        },
        numberSettings() {
            return this.settings.minimum !== null && this.settings.minimum !== undefined
                || this.settings.maximum !== null && this.settings.maximum !== undefined
                || this.settings.step !== null && this.settings.step !== undefined;
        },
        readOnlyValue() {
            if (this.value === null) return 'null';
            if (typeof this.value === 'object') return JSON.stringify(this.value);
            return String(this.value);
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
            this.pending = false;
        },
        commitValue(value) {
            // hold what was sent on screen until the answer arrives: the scene
            // status carrying it back is debounced behind an autosave, and
            // falling back to the prop meanwhile shows the old value again
            if (this.pending && Object.is(value, this.draftValue)) return;
            if (!this.pending && Object.is(value, this.value)) {
                this.clearDraft();
                return;
            }
            this.draftValue = value;
            this.hasDraft = true;
            this.pending = true;
            this.$emit('update-value', value);
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

            this.commitValue(next);
        },
    },
};
</script>

<template>
    <div class="mt-3">
        <div class="text-body-small text-muted" v-if="label">
            <strong>{{ label }}</strong>
        </div>
        <div class="text-body-small text-medium-emphasis mb-2 d-flex align-center" v-if="description || choices.length > 1">
            <span v-if="description">{{ description }}</span>
            <v-btn
                v-if="choices.length > 1"
                size="x-small"
                variant="text"
                color="secondary"
                prepend-icon="mdi-scale-balance"
                :class="description ? 'ml-2' : ''"
                @click="equalize"
            >Equalize</v-btn>
        </div>
        <div v-for="choice in choices" :key="choice.value" class="d-flex align-center">
            <div class="weight-label text-body-small" :class="{ 'text-medium-emphasis': isDisabled(choice.value) }">
                {{ choice.label }}
                <v-icon
                    v-if="isLockedAtFull(choice.value)"
                    size="x-small"
                    color="muted"
                    icon="mdi-lock"
                    class="ml-1"
                ></v-icon>
                <v-icon
                    v-else-if="!isDisabled(choice.value) && lastTouched === choice.value"
                    size="x-small"
                    color="muted"
                    icon="mdi-pin"
                    class="ml-1"
                ></v-icon>
            </div>
            <v-slider
                :model-value="weightFor(choice.value)"
                @update:modelValue="onSlide(choice.value, $event)"
                @end="lastTouched = choice.value"
                :min="0"
                :max="1"
                :step="step"
                density="compact"
                color="primary"
                hide-details
                thumb-label="always"
                class="flex-grow-1"
            >
                <template v-slot:thumb-label="{ modelValue }">
                    {{ formatWeight(modelValue) }}
                </template>
            </v-slider>
        </div>
    </div>
</template>

<script>
export default {
    props: {
        modelValue: {
            type: Object,
            required: true,
        },
        choices: {
            type: Array,
            required: true,
        },
        label: {
            type: String,
            required: false,
        },
        description: {
            type: String,
            required: false,
        },
        step: {
            type: Number,
            required: false,
            default: 0.05,
        },
    },
    emits: ['update:modelValue'],
    data() {
        return {
            lastTouched: null,
        };
    },
    methods: {
        weightFor(key) {
            const v = this.modelValue?.[key];
            return typeof v === 'number' ? v : 0;
        },
        isDisabled(key) {
            // Tolerate sub-step float drift in externally-seeded models so the
            // muted-label affordance doesn't silently vanish for near-zero values.
            return this.weightFor(key) < this.step / 2;
        },
        isLockedAtFull(key) {
            if (this.weightFor(key) <= 1 - this.step / 2) return false;
            return this.choices.every(c => c.value === key || this.isDisabled(c.value));
        },
        formatWeight(v) {
            const precision = Math.max(0, Math.round(-Math.log10(this.step)));
            return Number(v).toFixed(precision);
        },
        equalize() {
            const keys = this.choices.map(c => c.value);
            if (keys.length === 0) return;
            const precision = Math.max(0, Math.round(-Math.log10(this.step)));
            const share = 1 / keys.length;
            const rounded = {};
            keys.forEach(k => { rounded[k] = parseFloat(share.toFixed(precision + 2)); });
            // Absorb rounding drift on the first key so the sum stays at 1.
            const drift = 1 - Object.values(rounded).reduce((a, b) => a + b, 0);
            rounded[keys[0]] = parseFloat((rounded[keys[0]] + drift).toFixed(precision + 2));
            // Clear the pin so subsequent drags start from a clean state.
            this.lastTouched = null;
            this.$emit('update:modelValue', rounded);
        },
        onSlide(changedKey, newValue) {
            const keys = this.choices.map(c => c.value);
            const current = {};
            keys.forEach(k => { current[k] = this.weightFor(k); });

            // Frozen keys retain their value during this update.
            //   - Disabled (=0): the user parked them out of the balance,
            //     so they no longer absorb redistribution.
            //   - Pinned (last-touched, still enabled): held steady while
            //     a different slider is being adjusted, but only when at
            //     least one other key remains free to absorb the change.
            const disabledKeys = keys.filter(k => k !== changedKey && current[k] === 0);
            let pinnedKey = (this.lastTouched && this.lastTouched !== changedKey && current[this.lastTouched] > 0)
                ? this.lastTouched
                : null;
            if (pinnedKey) {
                const freeIfPinned = keys.filter(
                    k => k !== changedKey && k !== pinnedKey && !disabledKeys.includes(k),
                );
                if (freeIfPinned.length === 0) pinnedKey = null;
            }
            const frozenKeys = pinnedKey ? disabledKeys.concat([pinnedKey]) : disabledKeys;
            const frozenSum = frozenKeys.reduce((acc, k) => acc + current[k], 0);
            const freeKeys = keys.filter(k => k !== changedKey && !frozenKeys.includes(k));

            // With no free key, the changed slider is forced to 1 - frozenSum.
            // When every other key is disabled, this locks it at 1.0.
            const clamped = freeKeys.length === 0
                ? 1 - frozenSum
                : Math.max(0, Math.min(1 - frozenSum, newValue));

            const freeBudget = Math.max(0, 1 - clamped - frozenSum);
            const freeSum = freeKeys.reduce((acc, k) => acc + current[k], 0);

            const next = { [changedKey]: clamped };
            frozenKeys.forEach(k => { next[k] = current[k]; });

            // Free keys all have current[k] > 0 by construction (zero-valued
            // non-changed keys are frozen), so freeSum > 0 whenever freeKeys
            // is non-empty.
            freeKeys.forEach(k => { next[k] = (current[k] / freeSum) * freeBudget; });

            // Round to step precision. Absorb sub-step drift on the largest
            // non-frozen key so frozen values stay put. The changed slider
            // itself is always eligible, which is what soaks up drift in the
            // locked-at-1.0 case where freeKeys is empty.
            const rounded = {};
            const precision = Math.max(0, Math.round(-Math.log10(this.step)));
            keys.forEach(k => { rounded[k] = parseFloat(next[k].toFixed(precision + 2)); });
            const drift = 1 - Object.values(rounded).reduce((a, b) => a + b, 0);
            const absorbCandidates = [changedKey, ...freeKeys];
            const driftKey = absorbCandidates.reduce(
                (best, k) => (rounded[k] > rounded[best] ? k : best),
                absorbCandidates[0],
            );
            rounded[driftKey] = parseFloat((rounded[driftKey] + drift).toFixed(precision + 2));

            // Skip the emit if nothing actually changed — e.g., a drag attempt
            // on the locked-at-1.0 slider would otherwise re-emit an identical
            // model on every tick.
            if (keys.every(k => rounded[k] === current[k])) return;

            this.$emit('update:modelValue', rounded);
        },
    },
};
</script>

<style scoped>
.weight-label {
    width: 180px;
    flex-shrink: 0;
    padding-right: 12px;
}
</style>

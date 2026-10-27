<template>
    <div class="entry-visibility d-flex flex-wrap align-start" :class="{ 'entry-visibility-list': mode === 'list' }">
        <div class="entry-visibility-mode">
            <v-select
                :model-value="mode"
                :items="modes"
                item-title="label"
                item-value="value"
                label="Known by"
                density="compact"
                variant="underlined"
                hide-details
                :disabled="disabled"
                @update:model-value="setMode">
                <template v-slot:prepend-inner>
                    <v-icon size="small" :icon="modeIcon"></v-icon>
                </template>
            </v-select>
            <v-tooltip activator="parent" location="top">{{ hint }}</v-tooltip>
        </div>
        <v-autocomplete
            v-if="mode === 'list'"
            class="entry-visibility-characters"
            :model-value="characters"
            :items="characterNames"
            label="Characters"
            placeholder="Choose characters"
            persistent-placeholder
            density="compact"
            variant="underlined"
            hide-details
            multiple
            chips
            closable-chips
            :disabled="disabled"
            @update:model-value="setCharacters"></v-autocomplete>
    </div>
</template>

<script>
export default {
    name: 'EntryVisibilitySelect',
    props: {
        modelValue: Object,
        characterNames: {
            type: Array,
            default: () => [],
        },
        ownerLabel: {
            type: String,
            default: 'the owner',
        },
        disabled: Boolean,
        disabledHint: String,
    },
    emits: ['update:modelValue'],
    computed: {
        mode() {
            return this.modelValue?.mode || 'everyone';
        },
        characters() {
            return this.modelValue?.characters || [];
        },
        modes() {
            return [
                { label: 'Everyone', value: 'everyone' },
                { label: this.ownerLabel === 'nobody' ? 'Nobody' : `Only ${this.ownerLabel}`, value: 'owner' },
                { label: 'Specific characters', value: 'list' },
            ];
        },
        modeIcon() {
            return {
                everyone: 'mdi-earth',
                owner: 'mdi-lock',
                list: 'mdi-account-multiple',
            }[this.mode];
        },
        hint() {
            if (this.disabled && this.disabledHint) return this.disabledHint;
            return {
                everyone: 'Every character can draw on this entry.',
                owner: this.ownerLabel === 'nobody'
                    ? 'Keep this entry hidden from characters, unless you explicitly give them access.'
                    : `Keep this entry private to ${this.ownerLabel}, unless you explicitly give another character access.`,
                list: 'Share this entry with the chosen characters and its owner.',
            }[this.mode];
        },
    },
    methods: {
        setMode(mode) {
            this.$emit('update:modelValue', { mode, characters: mode === 'list' ? this.characters : [] });
        },
        setCharacters(characters) {
            this.$emit('update:modelValue', { mode: 'list', characters });
        },
    },
}
</script>

<style scoped>
.entry-visibility {
    gap: 12px 16px;
    max-width: 100%;
    width: 210px;
}

.entry-visibility-list {
    width: 100%;
    max-width: 520px;
    container-type: inline-size;
}

.entry-visibility-mode {
    flex: 0 1 210px;
    min-width: 0;
}

.entry-visibility-characters {
    flex: 1 1 200px;
    min-width: 0;
}

@container (max-width: 425px) {
    .entry-visibility-mode {
        flex-basis: 100%;
    }
}
</style>
